import assert from "node:assert/strict";
import test from "node:test";

import { classifyHttpError } from "./errors.js";

test("HTTP body parser client errors retain their 4xx status", () => {
  assert.deepEqual(classifyHttpError(Object.assign(new Error(), { status: 400 })), {
    status: 400,
    message: "Invalid request body",
  });
  assert.deepEqual(classifyHttpError(Object.assign(new Error(), { status: 413 })), {
    status: 413,
    message: "Request body too large",
  });
  assert.deepEqual(classifyHttpError(Object.assign(new Error(), { status: 403 })), {
    status: 403,
    message: "Request origin is not allowed",
  });
});

test("unexpected server errors remain generic", () => {
  assert.deepEqual(classifyHttpError(new Error("private detail")), {
    status: 500,
    message: "Internal server error",
  });
});
