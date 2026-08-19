import assert from "node:assert/strict";
import test from "node:test";

import {
  buildAgentCard,
  parseA2AMessage,
  parseA2ATaskId,
  toA2ATask,
} from "./a2a.js";

test("A2A message parsing bounds and joins text parts", () => {
  const parsed = parseA2AMessage({
    message: {
      messageId: "message-1",
      role: "ROLE_USER",
      parts: [{ text: "first" }, { text: "second" }],
      contextId: "context-1",
    },
  });
  assert.equal(parsed.textContent, "first\nsecond");
  assert.equal(parsed.contextId, "context-1");
  assert.equal(parsed.messageId, "message-1");

  assert.throws(
    () =>
      parseA2AMessage({
        message: {
          messageId: "message-2",
          role: "ROLE_USER",
          parts: [{ text: "é".repeat(5_001) }],
        },
      }),
    /10,000 UTF-8 bytes/
  );
  assert.throws(
    () =>
      parseA2AMessage({
        message: {
          messageId: "message-3",
          role: "ROLE_USER",
          parts: "not-an-array",
        },
      }),
    /invalid_type/
  );
  assert.throws(
    () =>
      parseA2AMessage({
        message: { role: "ROLE_USER", parts: [{ text: "missing id" }] },
      }),
    /Required/
  );
  assert.throws(
    () =>
      parseA2AMessage({
        message: {
          messageId: "message-4",
          role: "ROLE_AGENT",
          parts: [{ text: "wrong role" }],
        },
      }),
    /Invalid literal value/
  );
  assert.throws(
    () =>
      parseA2AMessage({
        message: {
          messageId: "message-5",
          role: "ROLE_USER",
          parts: [{ data: { unsafe: true } }],
        },
      }),
    /Required/
  );
});

test("A2A task ids are bounded opaque identifiers", () => {
  assert.equal(parseA2ATaskId({ id: "task-opaque-id" }), "task-opaque-id");
  assert.throws(() => parseA2ATaskId({ id: "" }), /too_small/);
  assert.throws(() => parseA2ATaskId({ id: "x".repeat(257) }), /too_big/);
});

test("agent card is absolute, secured, complete, and does not overclaim v1", () => {
  const card = buildAgentCard("https://agent.example.test/a2a");
  assert.equal(card.supportedInterfaces[0].url, "https://agent.example.test/a2a");
  assert.equal(card.supportedInterfaces[0].protocolVersion, "0.0");
  assert.deepEqual(card.defaultInputModes, ["text/plain"]);
  assert.deepEqual(card.defaultOutputModes, ["text/plain"]);
  assert.ok(card.skills[0].tags.length > 0);
  assert.equal(
    card.securitySchemes.apiKeyHeader.apiKeySecurityScheme.name,
    "X-API-Key"
  );
  assert.deepEqual(card.securityRequirements, [
    { schemes: { apiKeyHeader: { list: [] } } },
  ]);

  assert.throws(() => buildAgentCard("/a2a"), /absolute HTTP\(S\) URL/);
  assert.throws(
    () => buildAgentCard("https://secret@example.test/a2a"),
    /without credentials/
  );
});

test("failed tasks use a complete server Message in TaskStatus", () => {
  const task = toA2ATask({
    id: "task-1",
    description: "inspect",
    state: "failed",
    result: null,
    error: "provider failed",
    metadata: { contextId: "context-1", messageId: "message-1" },
    created_at: "2026-08-17T00:00:00.000Z",
    updated_at: "2026-08-17T00:00:01.000Z",
  });
  assert.deepEqual(task.status.message, {
    messageId: "task-1-status-2026-08-17T00:00:01.000Z",
    contextId: "context-1",
    taskId: "task-1",
    role: "ROLE_AGENT",
    parts: [{ text: "provider failed" }],
  });
});
