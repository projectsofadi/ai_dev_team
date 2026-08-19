import assert from "node:assert/strict";
import { chmod, mkdtemp, rm, writeFile } from "node:fs/promises";
import type { AddressInfo } from "node:net";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { once } from "node:events";
import { setTimeout as delay } from "node:timers/promises";
import test from "node:test";

type RpcResponse = {
  jsonrpc?: string;
  id?: string | number | null;
  result?: Record<string, unknown>;
  error?: {
    code: number;
    message: string;
    data?: Record<string, unknown>;
  };
};

const temporaryRoot = await mkdtemp(join(tmpdir(), "ai-dev-team-a2a-"));
const slowBridge = join(temporaryRoot, "slow-bridge.sh");
const failedBridge = join(temporaryRoot, "failed-bridge.sh");
await writeFile(slowBridge, "#!/bin/sh\nsleep 30\n", { mode: 0o700 });
await writeFile(
  failedBridge,
  `#!/bin/sh
task_id=""
while [ "$#" -gt 0 ]; do
  if [ "$1" = "--task-id" ]; then
    shift
    task_id="$1"
  fi
  shift
done
printf 'AI_DEV_TEAM_RESULT={"id":"%s","state":"failed","result":null,"error":"fixture failure"}\\n' "$task_id"
exit 1
`,
  { mode: 0o700 }
);
await chmod(slowBridge, 0o700);
await chmod(failedBridge, 0o700);

const environmentKeys = [
  "API_HOST",
  "API_PORT",
  "API_KEY",
  "A2A_PUBLIC_URL",
  "AGENT_WORKSPACE",
  "PYTHON_EXECUTABLE",
] as const;
const priorEnvironment = new Map(
  environmentKeys.map((key) => [key, process.env[key]])
);
process.env.API_HOST = "127.0.0.1";
process.env.API_PORT = "0";
process.env.API_KEY = "a2a-test-key";
process.env.A2A_PUBLIC_URL = "https://agent.example.test/a2a";
process.env.AGENT_WORKSPACE = temporaryRoot;
process.env.PYTHON_EXECUTABLE = failedBridge;

const { server } = await import("../index.js");
if (!server.listening) await once(server, "listening");
const address = server.address() as AddressInfo;
const baseUrl = `http://127.0.0.1:${address.port}`;

test.after(async () => {
  await new Promise<void>((resolve, reject) => {
    server.close((error) => (error ? reject(error) : resolve()));
  });
  for (const [key, value] of priorEnvironment) {
    if (value === undefined) delete process.env[key];
    else process.env[key] = value;
  }
  await rm(temporaryRoot, { recursive: true, force: true });
});

async function rpc(
  payload: unknown,
  options: { authenticated?: boolean; raw?: boolean } = {}
): Promise<{ status: number; body: RpcResponse }> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (options.authenticated !== false) headers["X-API-Key"] = "a2a-test-key";
  const response = await fetch(`${baseUrl}/a2a`, {
    method: "POST",
    headers,
    body: options.raw ? String(payload) : JSON.stringify(payload),
  });
  return { status: response.status, body: (await response.json()) as RpcResponse };
}

async function sendMessage(messageId: string): Promise<RpcResponse> {
  return (
    await rpc({
      jsonrpc: "2.0",
      id: messageId,
      method: "SendMessage",
      params: {
        message: {
          messageId,
          role: "ROLE_USER",
          parts: [{ text: "inspect this task", mediaType: "text/plain" }],
        },
      },
    })
  ).body;
}

async function getTask(taskId: string): Promise<RpcResponse> {
  return (
    await rpc({
      jsonrpc: "2.0",
      id: `get-${taskId}`,
      method: "GetTask",
      params: { id: taskId },
    })
  ).body;
}

async function waitForState(
  taskId: string,
  expectedState: string
): Promise<RpcResponse> {
  for (let attempt = 0; attempt < 100; attempt += 1) {
    const response = await getTask(taskId);
    const status = response.result?.status as Record<string, unknown> | undefined;
    if (status?.state === expectedState) return response;
    await delay(10);
  }
  throw new Error(`Task ${taskId} did not reach ${expectedState}`);
}

test("public root Agent Card is complete while the A2A method endpoint is authenticated", async () => {
  const cardResponse = await fetch(
    `${baseUrl}/.well-known/agent-card.json`
  );
  assert.equal(cardResponse.status, 200);
  const card = (await cardResponse.json()) as Record<string, unknown>;
  const interfaces = card.supportedInterfaces as Array<Record<string, unknown>>;
  assert.equal(interfaces[0].url, "https://agent.example.test/a2a");
  assert.equal(interfaces[0].protocolVersion, "0.0");
  assert.deepEqual(card.defaultInputModes, ["text/plain"]);
  assert.deepEqual(card.defaultOutputModes, ["text/plain"]);
  assert.ok(Array.isArray((card.skills as Array<Record<string, unknown>>)[0].tags));
  assert.ok(card.securitySchemes);
  assert.ok(card.securityRequirements);

  const unauthenticated = await rpc(
    { jsonrpc: "2.0", id: 1, method: "GetTask", params: { id: "missing" } },
    { authenticated: false }
  );
  assert.equal(unauthenticated.status, 401);

  const malformedUnauthenticated = await rpc("{", {
    authenticated: false,
    raw: true,
  });
  assert.equal(malformedUnauthenticated.status, 401);

  const legacyCard = await fetch(`${baseUrl}/a2a/.well-known/agent-card.json`);
  assert.equal(legacyCard.status, 401);
});

test("JSON-RPC parse, request, method, and SendMessage validation errors are standard", async () => {
  const malformed = await rpc('{"jsonrpc":', { raw: true });
  assert.equal(malformed.status, 400);
  assert.deepEqual(malformed.body, {
    jsonrpc: "2.0",
    id: null,
    error: { code: -32700, message: "Parse error" },
  });

  const trailingSlashMalformed = await fetch(`${baseUrl}/a2a/`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-API-Key": "a2a-test-key",
    },
    body: "{",
  });
  assert.equal(trailingSlashMalformed.status, 400);
  assert.equal(
    ((await trailingSlashMalformed.json()) as RpcResponse).error?.code,
    -32700
  );

  const invalidRequest = await rpc({ jsonrpc: "1.0", id: 1, method: "GetTask" });
  assert.equal(invalidRequest.status, 400);
  assert.equal(invalidRequest.body.error?.code, -32600);

  const unknownMethod = await rpc({
    jsonrpc: "2.0",
    id: 2,
    method: "NotImplemented",
  });
  assert.equal(unknownMethod.body.error?.code, -32601);
  assert.equal(unknownMethod.body.error?.message, "Method not found");

  for (const message of [
    { role: "ROLE_USER", parts: [{ text: "missing id" }] },
    { messageId: "wrong-role", role: "ROLE_AGENT", parts: [{ text: "no" }] },
    { messageId: "no-text", role: "ROLE_USER", parts: [{ data: { a: 1 } }] },
  ]) {
    const invalidMessage = await rpc({
      jsonrpc: "2.0",
      id: "invalid-message",
      method: "SendMessage",
      params: { message },
    });
    assert.equal(invalidMessage.body.error?.code, -32602);
  }
});

test("SendMessage wraps its Task while GetTask and CancelTask return Tasks directly", async () => {
  process.env.PYTHON_EXECUTABLE = failedBridge;
  const sent = await sendMessage("failure-message");
  const sendResult = sent.result as { task: Record<string, unknown> };
  assert.ok(sendResult.task);
  const failedTaskId = sendResult.task.id as string;

  const fetched = await waitForState(failedTaskId, "TASK_STATE_FAILED");
  assert.equal(fetched.result?.id, failedTaskId);
  assert.equal(Object.hasOwn(fetched.result || {}, "task"), false);
  const failedStatus = fetched.result?.status as Record<string, unknown>;
  const statusMessage = failedStatus.message as Record<string, unknown>;
  assert.equal(statusMessage.role, "ROLE_AGENT");
  assert.equal(statusMessage.taskId, failedTaskId);
  assert.equal(statusMessage.contextId, fetched.result?.contextId);
  assert.ok(statusMessage.messageId);

  const terminalCancellation = await rpc({
    jsonrpc: "2.0",
    id: "terminal-cancel",
    method: "CancelTask",
    params: { id: failedTaskId },
  });
  assert.equal(terminalCancellation.body.error?.code, -32002);

  process.env.PYTHON_EXECUTABLE = slowBridge;
  const cancellable = await sendMessage("cancel-message");
  const taskId = (cancellable.result as { task: Record<string, unknown> }).task
    .id as string;
  const cancelled = await rpc({
    jsonrpc: "2.0",
    id: "cancel-running",
    method: "CancelTask",
    params: { id: taskId },
  });
  assert.equal(cancelled.body.result?.id, taskId);
  assert.equal(Object.hasOwn(cancelled.body.result || {}, "task"), false);
  const cancelledStatus = cancelled.body.result?.status as Record<string, unknown>;
  assert.equal(cancelledStatus.state, "TASK_STATE_CANCELED");
});
