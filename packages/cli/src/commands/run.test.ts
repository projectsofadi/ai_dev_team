import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { createServer } from "node:http";
import type { AddressInfo } from "node:net";
import { once } from "node:events";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { WebSocketServer } from "ws";

import { terminalTaskError } from "./run.js";

test("only a completed task is a successful terminal outcome", () => {
  assert.equal(terminalTaskError("completed"), null);
  assert.match(terminalTaskError("failed", "provider failed")!.message, /provider failed/);
  assert.match(terminalTaskError("cancelled")!.message, /cancelled/);
  assert.equal(terminalTaskError("executing"), null);
});

const compiledCliPath = fileURLToPath(new URL("../index.js", import.meta.url));
const taskId = "123e4567-e89b-12d3-a456-426614174000";

async function runCompiledCliScenario(
  state: "completed" | "failed" | "cancelled"
): Promise<{ code: number | null; signal: NodeJS.Signals | null; output: string }> {
  let httpAuthorization: string | undefined;
  let websocketAuthorization: string | undefined;
  let subscribedTaskId: string | undefined;
  const httpServer = createServer((request, response) => {
    if (request.method !== "POST" || request.url !== "/api/tasks") {
      response.writeHead(404).end();
      return;
    }
    httpAuthorization = request.headers.authorization;
    request.resume();
    request.on("end", () => {
      response.writeHead(201, { "Content-Type": "application/json" });
      response.end(JSON.stringify({ id: taskId, state: "submitted" }));
    });
  });
  const websocketServer = new WebSocketServer({ server: httpServer, path: "/ws" });
  websocketServer.on("connection", (socket, request) => {
    websocketAuthorization = request.headers.authorization;
    socket.on("message", (raw) => {
      const message = JSON.parse(raw.toString()) as {
        type: string;
        task_id: string;
      };
      subscribedTaskId = message.task_id;
      socket.send(
        JSON.stringify({
          type: "task_update",
          task_id: taskId,
          timestamp: "2026-08-17T00:00:00.000Z",
          data: {
            state,
            ...(state === "failed" ? { error: "fixture failed" } : {}),
          },
        })
      );
    });
  });

  httpServer.listen(0, "127.0.0.1");
  await once(httpServer, "listening");
  const { port } = httpServer.address() as AddressInfo;
  const child = spawn(
    process.execPath,
    [
      compiledCliPath,
      "run",
      "loopback integration",
      "--server",
      `http://127.0.0.1:${port}`,
      "--api-key",
      "integration-key",
      "--watch",
    ],
    {
      env: { ...process.env, NO_COLOR: "1" },
      stdio: ["ignore", "pipe", "pipe"],
    }
  );
  let stdout = "";
  let stderr = "";
  child.stdout.on("data", (chunk: Buffer) => {
    stdout += chunk.toString("utf8");
  });
  child.stderr.on("data", (chunk: Buffer) => {
    stderr += chunk.toString("utf8");
  });

  let timeout: NodeJS.Timeout | undefined;
  try {
    const outcome = await Promise.race([
      new Promise<{ code: number | null; signal: NodeJS.Signals | null }>(
        (resolve, reject) => {
          child.once("error", reject);
          child.once("close", (code, signal) => resolve({ code, signal }));
        }
      ),
      new Promise<never>((_, reject) => {
        timeout = setTimeout(() => {
          child.kill("SIGKILL");
          reject(new Error(`compiled CLI did not exit for ${state}`));
        }, 5_000);
      }),
    ]);
    assert.equal(httpAuthorization, "Bearer integration-key");
    assert.equal(websocketAuthorization, "Bearer integration-key");
    assert.equal(subscribedTaskId, taskId);
    return { ...outcome, output: stdout + stderr };
  } finally {
    if (timeout) clearTimeout(timeout);
    for (const client of websocketServer.clients) client.terminate();
    await new Promise<void>((resolve) => websocketServer.close(() => resolve()));
    await new Promise<void>((resolve, reject) => {
      httpServer.close((error) => (error ? reject(error) : resolve()));
    });
  }
}

test("compiled CLI maps loopback HTTP and WebSocket terminal states to process exits", async () => {
  const completed = await runCompiledCliScenario("completed");
  assert.equal(completed.code, 0);
  assert.equal(completed.signal, null);

  const failed = await runCompiledCliScenario("failed");
  assert.equal(failed.code, 1);
  assert.equal(failed.signal, null);
  assert.equal(failed.output.split("fixture failed").length - 1, 1);

  const cancelled = await runCompiledCliScenario("cancelled");
  assert.equal(cancelled.code, 1);
  assert.equal(cancelled.signal, null);
  assert.equal(
    cancelled.output.split("Task ended in state: cancelled").length - 1,
    1
  );
});
