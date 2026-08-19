/**
 * A2A (Agent-to-Agent) JSON-RPC 2.0 endpoint.
 *
 * Implements an experimental subset of the A2A v1 JSON shapes:
 * - Agent Card discovery at /.well-known/agent-card.json
 * - SendMessage for task submission
 * - GetTask for status polling
 * - CancelTask for non-terminal tasks
 *
 * This adapter intentionally does not advertise A2A v1 conformance because
 * the mandatory ListTasks operation is not implemented.
 */

import { Router, Request, Response } from "express";
import { v4 as uuidv4 } from "uuid";
import { z } from "zod";
import {
  cancelTaskById,
  getTaskById,
  submitTask,
  type TaskRecord,
} from "./tasks.js";

const a2aRouter = Router();

const RpcIdSchema = z.union([z.string().max(256), z.number().finite(), z.null()]);
const JsonRpcRequestSchema = z
  .object({
    jsonrpc: z.literal("2.0"),
    id: RpcIdSchema,
    method: z.string().min(1).max(128),
    params: z.record(z.unknown()).default({}),
  })
  .strict();
const TextPartSchema = z
  .object({
    text: z.string().min(1).max(10_000),
    mediaType: z.literal("text/plain").optional(),
  })
  .strict();
const SendMessageParamsSchema = z
  .object({
    tenant: z.string().min(1).max(256).optional(),
    message: z
      .object({
        messageId: z.string().min(1).max(256),
        contextId: z.string().min(1).max(256).optional(),
        taskId: z.never().optional(),
        role: z.literal("ROLE_USER"),
        parts: z.array(TextPartSchema).min(1).max(64),
        metadata: z.record(z.unknown()).optional(),
        extensions: z.array(z.string().min(1).max(2_048)).max(64).optional(),
        referenceTaskIds: z.array(z.string().min(1).max(256)).max(64).optional(),
      })
      .strict(),
    configuration: z.record(z.unknown()).optional(),
    metadata: z.record(z.unknown()).optional(),
  })
  .strict();
const TaskIdParamsSchema = z.object({ id: z.string().min(1).max(256) });

type RpcId = z.infer<typeof RpcIdSchema>;

export function parseA2AMessage(params: unknown): {
  textContent: string;
  contextId: string;
  messageId: string;
} {
  const parsed = SendMessageParamsSchema.parse(params);
  const textContent = parsed.message.parts.map((part) => part.text).join("\n");
  if (!textContent || Buffer.byteLength(textContent, "utf8") > 10_000) {
    throw new Error("Message text must contain 1-10,000 UTF-8 bytes");
  }
  return {
    textContent,
    contextId: parsed.message.contextId || uuidv4(),
    messageId: parsed.message.messageId,
  };
}

export function parseA2ATaskId(params: unknown): string {
  return TaskIdParamsSchema.parse(params).id;
}

interface A2ATask {
  id: string;
  contextId: string;
  status: {
    state: string;
    message?: {
      messageId: string;
      contextId: string;
      taskId: string;
      role: "ROLE_AGENT";
      parts: Array<{ text: string }>;
    };
    timestamp: string;
  };
  artifacts: Array<{
    artifactId: string;
    parts: Array<{ text: string }>;
  }>;
  history: Array<{
    messageId: string;
    contextId?: string;
    role: string;
    parts: Array<{ text: string }>;
  }>;
}

function normalizeA2AEndpoint(rawUrl: string): string {
  let parsed: URL;
  try {
    parsed = new URL(rawUrl);
  } catch {
    throw new Error("A2A_PUBLIC_URL must be an absolute HTTP(S) URL");
  }
  if (
    !["http:", "https:"].includes(parsed.protocol) ||
    parsed.username ||
    parsed.password ||
    parsed.search ||
    parsed.hash
  ) {
    throw new Error(
      "A2A_PUBLIC_URL must be an absolute HTTP(S) URL without credentials, query, or fragment"
    );
  }
  return parsed.toString().replace(/\/$/, "");
}

export function buildAgentCard(
  publicUrl =
    process.env.A2A_PUBLIC_URL ||
    `http://127.0.0.1:${process.env.API_PORT || "8080"}/a2a`
) {
  const apiKeyRequirement = {
    schemes: { apiKeyHeader: { list: [] as string[] } },
  };
  return {
    name: "AI Dev Team",
    description:
      "Experimental, non-conformant subset of A2A v1 task analysis. ListTasks and optional streaming/push operations are not implemented; HTTP writes remain approval-gated.",
    version: "0.1.0",
    supportedInterfaces: [
      {
        protocolBinding: "JSONRPC",
        // 0.0 is deliberate: the endpoint uses selected v1 shapes but does not
        // implement the complete mandatory v1 operation surface.
        protocolVersion: "0.0",
        url: normalizeA2AEndpoint(publicUrl),
      },
    ],
    capabilities: {
      streaming: false,
      pushNotifications: false,
      extendedAgentCard: false,
    },
    securitySchemes: {
      apiKeyHeader: {
        apiKeySecurityScheme: {
          description: "API key supplied in the X-API-Key request header",
          location: "header",
          name: "X-API-Key",
        },
      },
    },
    securityRequirements: [apiKeyRequirement],
    defaultInputModes: ["text/plain"],
    defaultOutputModes: ["text/plain"],
    skills: [
      {
        id: "dev-task",
        name: "Development Task Analysis",
        description:
          "Plan and inspect development tasks using the prototype's safe HTTP defaults",
        tags: ["software-development", "analysis"],
        inputModes: ["text/plain"],
        outputModes: ["text/plain"],
        securityRequirements: [apiKeyRequirement],
      },
    ],
  };
}

function a2aState(state: string): string {
  const states: Record<string, string> = {
    submitted: "TASK_STATE_SUBMITTED",
    executing: "TASK_STATE_WORKING",
    cancelling: "TASK_STATE_WORKING",
    completed: "TASK_STATE_COMPLETED",
    failed: "TASK_STATE_FAILED",
    cancelled: "TASK_STATE_CANCELED",
  };
  return states[state] || "TASK_STATE_UNKNOWN";
}

export function toA2ATask(task: TaskRecord): A2ATask {
  const contextId =
    typeof task.metadata.contextId === "string"
      ? task.metadata.contextId
      : task.id;
  const messageId =
    typeof task.metadata.messageId === "string"
      ? task.metadata.messageId
      : task.id;
  const statusMessage = task.error
    ? {
        messageId: `${task.id}-status-${task.updated_at}`,
        contextId,
        taskId: task.id,
        role: "ROLE_AGENT" as const,
        parts: [{ text: task.error }],
      }
    : undefined;

  return {
    id: task.id,
    contextId,
    status: {
      state: a2aState(task.state),
      message: statusMessage,
      timestamp: task.updated_at,
    },
    artifacts: task.result
      ? [{ artifactId: `${task.id}-result`, parts: [{ text: task.result }] }]
      : [],
    history: [
      {
        messageId,
        contextId,
        role: "ROLE_USER",
        parts: [{ text: task.description }],
      },
    ],
  };
}

export function agentCardHandler(_req: Request, res: Response): void {
  res.json(buildAgentCard());
}

// JSON-RPC dispatcher
a2aRouter.post("/", async (req: Request, res: Response) => {
  const request = JsonRpcRequestSchema.safeParse(req.body);
  if (!request.success) {
    res.status(400).json({
      jsonrpc: "2.0",
      id: null,
      error: { code: -32600, message: "Invalid JSON-RPC request" },
    });
    return;
  }
  const { id, method, params } = request.data;

  switch (method) {
    case "SendMessage":
      handleSendMessage(id, params, res);
      break;
    case "GetTask":
      handleGetTask(id, params, res);
      break;
    case "CancelTask":
      await handleCancelTask(id, params, res);
      break;
    default:
      res.json({
        jsonrpc: "2.0",
        id,
        error: {
          code: -32601,
          message: "Method not found",
        },
      });
  }
});

function handleSendMessage(rpcId: RpcId, params: unknown, res: Response) {
  let message: ReturnType<typeof parseA2AMessage>;
  try {
    message = parseA2AMessage(params);
  } catch {
    res.json({
      jsonrpc: "2.0",
      id: rpcId,
      error: { code: -32602, message: "Invalid SendMessage parameters" },
    });
    return;
  }

  const task = submitTask(message.textContent, {
    source: "a2a",
    contextId: message.contextId,
    messageId: message.messageId,
  });

  res.json({
    jsonrpc: "2.0",
    id: rpcId,
    result: { task: toA2ATask(task) },
  });
}

function handleGetTask(rpcId: RpcId, params: unknown, res: Response) {
  let taskId: string;
  try {
    taskId = parseA2ATaskId(params);
  } catch {
    res.json({
      jsonrpc: "2.0",
      id: rpcId,
      error: { code: -32602, message: "Invalid task id" },
    });
    return;
  }

  const task = getTaskById(taskId);
  if (!task) {
    res.json({
      jsonrpc: "2.0",
      id: rpcId,
      error: { code: -32001, message: "Task not found" },
    });
    return;
  }

  res.json({
    jsonrpc: "2.0",
    id: rpcId,
    result: toA2ATask(task),
  });
}

async function handleCancelTask(
  rpcId: RpcId,
  params: unknown,
  res: Response
) {
  let taskId: string;
  try {
    taskId = parseA2ATaskId(params);
  } catch {
    res.json({
      jsonrpc: "2.0",
      id: rpcId,
      error: { code: -32602, message: "Invalid task id" },
    });
    return;
  }
  const task = getTaskById(taskId);
  if (!task) {
    res.json({
      jsonrpc: "2.0",
      id: rpcId,
      error: { code: -32001, message: "Task not found" },
    });
    return;
  }

  if (["completed", "failed", "cancelled"].includes(task.state)) {
    res.json({
      jsonrpc: "2.0",
      id: rpcId,
      error: {
        code: -32002,
        message: "Task not cancelable",
        data: {
          details: [
            {
              "@type": "type.googleapis.com/google.rpc.ErrorInfo",
              reason: "TASK_NOT_CANCELABLE",
              domain: "a2a-protocol.org",
            },
          ],
        },
      },
    });
    return;
  }

  const cancelled = (await cancelTaskById(taskId))!;

  res.json({
    jsonrpc: "2.0",
    id: rpcId,
    result: toA2ATask(cancelled),
  });
}

export { a2aRouter };
