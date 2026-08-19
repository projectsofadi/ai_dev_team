import assert from "node:assert/strict";
import test from "node:test";

import { assertApiKeyConfigured, isAuthorized } from "./auth.js";

test("authentication fails closed without a configured key", () => {
  const previous = process.env.API_KEY;
  delete process.env.API_KEY;
  try {
    assert.equal(isAuthorized({ authorization: "Bearer anything" }), false);
    assert.throws(assertApiKeyConfigured, /API_KEY must be set/);
  } finally {
    if (previous === undefined) delete process.env.API_KEY;
    else process.env.API_KEY = previous;
  }
});

test("authentication accepts bearer and x-api-key credentials", () => {
  const previous = process.env.API_KEY;
  process.env.API_KEY = "correct-horse-battery-staple";
  try {
    assert.equal(
      isAuthorized({ authorization: "Bearer correct-horse-battery-staple" }),
      true
    );
    assert.equal(isAuthorized({ "x-api-key": "correct-horse-battery-staple" }), true);
    assert.equal(isAuthorized({ authorization: "Bearer wrong" }), false);
  } finally {
    if (previous === undefined) delete process.env.API_KEY;
    else process.env.API_KEY = previous;
  }
});

test("placeholder API keys are rejected at startup", () => {
  const previous = process.env.API_KEY;
  process.env.API_KEY = "your-api-key-here";
  try {
    assert.throws(assertApiKeyConfigured, /non-placeholder/);
  } finally {
    if (previous === undefined) delete process.env.API_KEY;
    else process.env.API_KEY = previous;
  }
});
