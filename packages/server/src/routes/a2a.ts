/**
 * A2A (Agent-to-Agent) JSON-RPC 2.0 endpoint.
 *
 * Implements a subset of the A2A v1.0 specification:
 * - Agent Card discovery at /.well-known/agent-card.json
 * - SendMessage for task submission
 * - GetTask for status polling
 */

import { Router, Request, Response } from "express";
import { v4 as uuidv4 } from "uuid";

const a2aRouter = Router();

interface A2ATask {
  id: string;
  contextId: string;
  status: {
    state: string;
    message?: { role: string; parts: Array<{ text: string }> };
    timestamp: string;
  };
  artifacts: Array<{
    artifactId: string;
    parts: Array<{ text: string }>;
  }>;
  history: Array<{
    messageId: string;
    role: string;
    parts: Array<{ text: string }>;
  }>;
}

const a2aTasks = new Map<string, A2ATask>();

const AGENT_CARD = {
  name: "AI Dev Team",
  description:
    "A multi-agent development team that plans, codes, reviews, and tests software.",
  version: "0.1.0",
  supportedInterfaces: [
    {
      protocolBinding: "JSONRPC",
      protocolVersion: "1.0",
      url: "/a2a",
    },
  ],
  capabilities: {
    streaming: false,
    pushNotifications: false,
  },
  skills: [
    {
      id: "dev-task",
      name: "Software Development",
      description: "Plan, implement, review, and test software changes",
    },
  ],
};

// Agent Card discovery
a2aRouter.get("/.well-known/agent-card.json", (_req: Request, res: Response) => {
  res.json(AGENT_CARD);
});

// JSON-RPC dispatcher
a2aRouter.post("/", (req: Request, res: Response) => {
  const { jsonrpc, id, method, params } = req.body;

  if (jsonrpc !== "2.0") {
    res.status(400).json({
      jsonrpc: "2.0",
      id,
      error: { code: -32600, message: "Invalid JSON-RPC version" },
    });
    return;
  }

  switch (method) {
    case "SendMessage":
      handleSendMessage(id, params, res);
      break;
    case "GetTask":
      handleGetTask(id, params, res);
      break;
    case "CancelTask":
      handleCancelTask(id, params, res);
      break;
    default:
      res.json({
        jsonrpc: "2.0",
        id,
        error: {
          code: -32004,
          message: `Unsupported method: ${method}`,
        },
      });
  }
});

function handleSendMessage(
  rpcId: string | number,
  params: Record<string, unknown>,
  res: Response
) {
  const message = params?.message as Record<string, unknown> | undefined;
  if (!message) {
    res.json({
      jsonrpc: "2.0",
      id: rpcId,
      error: { code: -32602, message: "Missing 'message' in params" },
    });
    return;
  }

  const parts = (message.parts as Array<{ text?: string }>) || [];
  const textContent = parts
    .map((p) => p.text || "")
    .filter(Boolean)
    .join("\n");

  const taskId = (message.taskId as string) || uuidv4();
  const contextId = (message.contextId as string) || uuidv4();
  const messageId = (message.messageId as string) || uuidv4();

  const task: A2ATask = {
    id: taskId,
    contextId,
    status: {
      state: "TASK_STATE_SUBMITTED",
      timestamp: new Date().toISOString(),
    },
    artifacts: [],
    history: [
      {
        messageId,
        role: "ROLE_USER",
        parts: [{ text: textContent }],
      },
    ],
  };

  a2aTasks.set(taskId, task);

  console.log(`A2A task created: ${taskId} — ${textContent.slice(0, 80)}`);

  res.json({
    jsonrpc: "2.0",
    id: rpcId,
    result: { task },
  });
}

function handleGetTask(
  rpcId: string | number,
  params: Record<string, unknown>,
  res: Response
) {
  const taskId = params?.id as string;
  if (!taskId) {
    res.json({
      jsonrpc: "2.0",
      id: rpcId,
      error: { code: -32602, message: "Missing 'id' in params" },
    });
    return;
  }

  const task = a2aTasks.get(taskId);
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
    result: { task },
  });
}

function handleCancelTask(
  rpcId: string | number,
  params: Record<string, unknown>,
  res: Response
) {
  const taskId = params?.id as string;
  const task = a2aTasks.get(taskId);
  if (!task) {
    res.json({
      jsonrpc: "2.0",
      id: rpcId,
      error: { code: -32001, message: "Task not found" },
    });
    return;
  }

  task.status = {
    state: "TASK_STATE_CANCELED",
    timestamp: new Date().toISOString(),
  };

  res.json({
    jsonrpc: "2.0",
    id: rpcId,
    result: { task },
  });
}

export { a2aRouter };
