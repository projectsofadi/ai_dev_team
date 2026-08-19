import assert from "node:assert/strict";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { setTimeout as delay } from "node:timers/promises";
import { fileURLToPath } from "node:url";

import {
  bridgeArguments,
  childEnvironment,
  parseBridgeResult,
  PythonTaskRunner,
} from "./task-runner.js";

const fixturePath = fileURLToPath(new URL("./task-runner-fixture.js", import.meta.url));

function fixtureRunner(
  mode: "success" | "completed-exit-one" | "malformed" | "flood" | "tree",
  pidFile?: string
): PythonTaskRunner {
  return new PythonTaskRunner((_taskId, _workspace) => [
    fixturePath,
    mode,
    _taskId,
    ...(pidFile ? [pidFile] : []),
  ]);
}

function processIsAlive(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ESRCH") return false;
    throw error;
  }
}

async function waitForGrandchildPid(pidFile: string): Promise<number> {
  for (let attempt = 0; attempt < 100; attempt += 1) {
    try {
      const pid = Number.parseInt(await readFile(pidFile, "utf8"), 10);
      if (Number.isInteger(pid) && pid > 0) return pid;
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
    }
    await delay(10);
  }
  throw new Error("tree fixture did not report its grandchild PID");
}

async function waitForProcessExit(pid: number): Promise<void> {
  for (let attempt = 0; attempt < 100; attempt += 1) {
    if (!processIsAlive(pid)) return;
    await delay(10);
  }
  throw new Error(`grandchild process ${pid} survived process-group termination`);
}

async function withRunnerEnvironment<T>(operation: () => Promise<T>): Promise<T> {
  const previousExecutable = process.env.PYTHON_EXECUTABLE;
  const previousWorkspace = process.env.AGENT_WORKSPACE;
  process.env.PYTHON_EXECUTABLE = process.execPath;
  process.env.AGENT_WORKSPACE = process.cwd();
  try {
    return await operation();
  } finally {
    if (previousExecutable === undefined) delete process.env.PYTHON_EXECUTABLE;
    else process.env.PYTHON_EXECUTABLE = previousExecutable;
    if (previousWorkspace === undefined) delete process.env.AGENT_WORKSPACE;
    else process.env.AGENT_WORKSPACE = previousWorkspace;
  }
}

test("bridge parser accepts the final matching result", () => {
  const result = parseBridgeResult(
    'noise\nAI_DEV_TEAM_RESULT={"id":"t1","state":"completed","result":"ok","error":null}\n',
    "t1"
  );
  assert.equal(result.state, "completed");
  assert.equal(result.result, "ok");

  const failure = parseBridgeResult(
    'AI_DEV_TEAM_RESULT={"id":"t1","state":"failed","result":null,"error":"provider failed"}',
    "t1",
    1
  );
  assert.equal(failure.state, "failed");
  assert.equal(failure.error, "provider failed");
});

test("bridge import is isolated from the untrusted workspace", () => {
  const args = bridgeArguments("task-1", "/untrusted/workspace");
  assert.deepEqual(args.slice(0, 4), ["-I", "-B", "-m", "ai_dev_team.bridge"]);
  assert.equal(args.includes("--description"), false);
  assert.equal(childEnvironment().PYTHONPATH, undefined);
});

test("bridge parser rejects mismatched ids and invalid states", () => {
  assert.throws(
    () =>
      parseBridgeResult(
        'AI_DEV_TEAM_RESULT={"id":"other","state":"completed","result":"ok","error":null}',
        "t1"
      ),
    /mismatched task id/
  );
  assert.throws(
    () =>
      parseBridgeResult(
        'AI_DEV_TEAM_RESULT={"id":"t1","state":"executing","result":null,"error":null}',
        "t1"
      ),
    /invalid task state/
  );
  assert.throws(
    () =>
      parseBridgeResult(
        'AI_DEV_TEAM_RESULT={"id":"t1","state":"completed","result":{"not":"text"},"error":null}',
        "t1"
      ),
    /invalid result payload/
  );
  assert.throws(
    () =>
      parseBridgeResult(
        'AI_DEV_TEAM_RESULT={"id":"t1","state":"completed","result":"ok","error":null,"extra":true}',
        "t1"
      ),
    /invalid result payload/
  );
});

test("bridge parser rejects state/result/error and exit-code contradictions", () => {
  for (const payload of [
    { id: "t1", state: "completed", result: null, error: null },
    { id: "t1", state: "completed", result: "ok", error: "unexpected" },
    { id: "t1", state: "failed", result: "unexpected", error: "failed" },
    { id: "t1", state: "failed", result: null, error: null },
    { id: "t1", state: "failed", result: null, error: "" },
  ]) {
    assert.throws(
      () =>
        parseBridgeResult(
          `AI_DEV_TEAM_RESULT=${JSON.stringify(payload)}`,
          "t1",
          payload.state === "failed" ? 1 : 0
        ),
      /invalid result payload/
    );
  }

  assert.throws(
    () =>
      parseBridgeResult(
        'AI_DEV_TEAM_RESULT={"id":"t1","state":"completed","result":"ok","error":null}',
        "t1",
        1
      ),
    /completed contradicts exit code 1/
  );
  assert.throws(
    () =>
      parseBridgeResult(
        'AI_DEV_TEAM_RESULT={"id":"t1","state":"failed","result":null,"error":"failed"}',
        "t1",
        0
      ),
    /failed contradicts exit code 0/
  );
  assert.throws(
    () =>
      parseBridgeResult(
        'AI_DEV_TEAM_RESULT={"id":"t1","state":"completed","result":"ok","error":null}',
        "t1",
        0,
        "SIGTERM"
      ),
    /terminated by SIGTERM/
  );
});

test("bridge parser does not echo malformed JSON content", () => {
  const secret = "BRIDGE-SECRET-MARKER";
  assert.throws(
    () =>
      parseBridgeResult(
        `AI_DEV_TEAM_RESULT={"private":"${secret}"`,
        "t1",
        1
      ),
    (error: unknown) => {
      assert.ok(error instanceof Error);
      assert.equal(error.message, "Python runner returned malformed JSON");
      assert.equal(error.message.includes(secret), false);
      return true;
    }
  );
});

test("runner requires an absolute configured workspace", () => {
  const previous = process.env.AGENT_WORKSPACE;
  process.env.AGENT_WORKSPACE = "relative/path";
  try {
    assert.throws(
      () => new PythonTaskRunner().validateConfiguration(),
      /absolute path/
    );
  } finally {
    if (previous === undefined) delete process.env.AGENT_WORKSPACE;
    else process.env.AGENT_WORKSPACE = previous;
  }
});

test("child environment passes provider credentials but not the server API key", () => {
  const previousServerKey = process.env.API_KEY;
  const previousProviderKey = process.env.OPENAI_API_KEY;
  process.env.API_KEY = "server-secret";
  process.env.OPENAI_API_KEY = "provider-secret";
  try {
    const env = childEnvironment();
    assert.equal(env.OPENAI_API_KEY, "provider-secret");
    assert.equal(env.API_KEY, undefined);
    assert.equal(env.REQUIRE_APPROVAL_FOR_WRITES, "true");
    assert.equal(env.REQUIRE_APPROVAL_FOR_SHELL, "true");
  } finally {
    if (previousServerKey === undefined) delete process.env.API_KEY;
    else process.env.API_KEY = previousServerKey;
    if (previousProviderKey === undefined) delete process.env.OPENAI_API_KEY;
    else process.env.OPENAI_API_KEY = previousProviderKey;
  }
});

test("runner validates framing from the compiled Node subprocess fixture", async () => {
  await withRunnerEnvironment(async () => {
    const result = await fixtureRunner("success").run("task-success", "inspect only");
    assert.equal(result.state, "completed");
    assert.equal(result.result, "fixture complete");
  });
});

test("runner rejects a completed payload from a real child that exits one", async () => {
  await withRunnerEnvironment(async () => {
    await assert.rejects(
      fixtureRunner("completed-exit-one").run("task-exit-one", "inspect only"),
      /completed contradicts exit code 1/
    );
  });
});

test("runner does not expose malformed child payloads through its rejection", async () => {
  await withRunnerEnvironment(async () => {
    await assert.rejects(
      fixtureRunner("malformed").run("task-malformed", "inspect only"),
      (error: unknown) => {
        assert.ok(error instanceof Error);
        assert.match(error.message, /Python runner returned malformed JSON/);
        assert.equal(error.message.includes("BRIDGE-SECRET-MARKER"), false);
        return true;
      }
    );
  });
});

test("runner cancellation kills the reported grandchild process", async () => {
  await withRunnerEnvironment(async () => {
    const temporaryRoot = await mkdtemp(join(tmpdir(), "ai-dev-team-tree-"));
    const pidFile = join(temporaryRoot, "grandchild.pid");
    const runner = fixtureRunner("tree", pidFile);
    let grandchildPid: number | undefined;
    try {
      const pending = runner.run("task-tree", "inspect only");
      grandchildPid = await waitForGrandchildPid(pidFile);
      assert.equal(processIsAlive(grandchildPid), true);
      assert.equal(await runner.cancel("task-tree"), true);
      await assert.rejects(
        pending,
        /exited without a result/
      );
      await waitForProcessExit(grandchildPid);
      assert.equal(processIsAlive(grandchildPid), false);
    } finally {
      await runner.cancel("task-tree").catch(() => false);
      if (grandchildPid !== undefined && processIsAlive(grandchildPid)) {
        process.kill(grandchildPid, "SIGKILL");
      }
      await rm(temporaryRoot, { recursive: true, force: true });
    }
  });
});

test("runner enforces its captured-output bound", async () => {
  await withRunnerEnvironment(async () => {
    await assert.rejects(
      fixtureRunner("flood").run("task-flood", "inspect only"),
      /output exceeded the 1 MB safety limit/
    );
  });
});

test("runner rejects concurrent work in the shared workspace", async () => {
  await withRunnerEnvironment(async () => {
    const runner = fixtureRunner("tree");
    const first = runner.run("task-first", "inspect only");
    await assert.rejects(
      runner.run("task-second", "inspect only"),
      /Another task is already running/
    );
    await runner.cancel("task-first");
    await assert.rejects(first, /exited without a result/);
  });
});
