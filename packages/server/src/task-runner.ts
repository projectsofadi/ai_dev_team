import { spawn, type ChildProcess } from "node:child_process";
import { realpathSync, statSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { isAbsolute, parse } from "node:path";
import { z } from "zod";

const RESULT_PREFIX = "AI_DEV_TEAM_RESULT=";
const MAX_CAPTURE_BYTES = 1_000_000;
const MAX_DESCRIPTION_BYTES = 10_000;
const TERMINATION_GRACE_MS = 2_000;
const BridgeResultSchema = z.discriminatedUnion("state", [
  z
    .object({
      id: z.string().min(1).max(256),
      state: z.literal("completed"),
      result: z.string().max(MAX_CAPTURE_BYTES),
      error: z.null(),
    })
    .strict(),
  z
    .object({
      id: z.string().min(1).max(256),
      state: z.literal("failed"),
      result: z.null(),
      error: z.string().min(1).max(MAX_CAPTURE_BYTES),
    })
    .strict(),
]);

const CHILD_ENV_KEYS = [
  "ANTHROPIC_API_KEY",
  "ANTHROPIC_MODEL",
  "DEFAULT_MODEL",
  "DEFAULT_PROVIDER",
  "MAX_AGENT_ITERATIONS",
  "MAX_COST_PER_TASK_USD",
  "MAX_TOKENS_PER_TASK",
  "OPENAI_API_KEY",
  "AGENT_TIMEOUT_SECONDS",
  "LANG",
  "LC_ALL",
  "PATH",
  "SSL_CERT_FILE",
] as const;

const TRUSTED_RUNTIME_CWD = realpathSync(fileURLToPath(new URL(".", import.meta.url)));

export function childEnvironment(): NodeJS.ProcessEnv {
  const env: NodeJS.ProcessEnv = {
    PYTHONUNBUFFERED: "1",
    REQUIRE_APPROVAL_FOR_WRITES: "true",
    REQUIRE_APPROVAL_FOR_SHELL: "true",
  };
  for (const key of CHILD_ENV_KEYS) {
    if (process.env[key] !== undefined) env[key] = process.env[key];
  }
  return env;
}

function taskTimeoutMs(): number {
  const configured = Number.parseInt(process.env.TASK_TIMEOUT_MS || "300000", 10);
  if (!Number.isFinite(configured)) return 300_000;
  return Math.min(Math.max(configured, 1_000), 3_600_000);
}

export interface BridgeResult {
  id: string;
  state: "completed" | "failed";
  result: string | null;
  error: string | null;
}

export function parseBridgeResult(
  stdout: string,
  taskId: string,
  exitCode = 0,
  signal: NodeJS.Signals | null = null
): BridgeResult {
  const resultLine = stdout
    .split(/\r?\n/)
    .filter((line) => line.startsWith(RESULT_PREFIX))
    .at(-1);
  if (!resultLine) {
    throw new Error("Python runner exited without a result");
  }

  let decoded: unknown;
  try {
    decoded = JSON.parse(resultLine.slice(RESULT_PREFIX.length));
  } catch {
    throw new Error("Python runner returned malformed JSON");
  }
  const parsed = BridgeResultSchema.safeParse(decoded);
  if (!parsed.success) {
    if (parsed.error.issues.some((issue) => issue.path[0] === "state")) {
      throw new Error("Python runner returned an invalid task state");
    }
    throw new Error("Python runner returned an invalid result payload");
  }
  const payload = parsed.data;
  if (payload.id !== taskId) {
    throw new Error("Python runner returned a mismatched task id");
  }
  if (signal !== null) {
    throw new Error(`Python runner was terminated by ${signal}`);
  }
  if (
    (payload.state === "completed" && exitCode !== 0) ||
    (payload.state === "failed" && exitCode === 0)
  ) {
    throw new Error(
      `Python runner state ${payload.state} contradicts exit code ${exitCode}`
    );
  }
  return payload;
}

export function bridgeArguments(taskId: string, workspace: string): string[] {
  return [
    "-I",
    "-B",
    "-m",
    "ai_dev_team.bridge",
    "--task-id",
    taskId,
    "--working-dir",
    workspace,
  ];
}

export type BridgeArgumentBuilder = (taskId: string, workspace: string) => string[];

export class PythonTaskRunner {
  private readonly children = new Map<string, ChildProcess>();
  private readonly terminations = new WeakMap<ChildProcess, Promise<void>>();

  constructor(
    private readonly buildBridgeArguments: BridgeArgumentBuilder = bridgeArguments
  ) {}

  validateConfiguration(): string {
    const workspace = process.env.AGENT_WORKSPACE;
    if (!workspace || !isAbsolute(workspace)) {
      throw new Error("AGENT_WORKSPACE must be configured as an absolute path");
    }
    const resolved = realpathSync(workspace);
    if (resolved === parse(resolved).root || !statSync(resolved).isDirectory()) {
      throw new Error("AGENT_WORKSPACE must be an existing, non-root directory");
    }
    return resolved;
  }

  run(taskId: string, description: string): Promise<BridgeResult> {
    const workspace = this.validateConfiguration();
    if (this.children.has(taskId)) {
      return Promise.reject(new Error(`Task ${taskId} is already running`));
    }
    if (this.children.size >= 1) {
      return Promise.reject(
        new Error("Another task is already running in the shared workspace")
      );
    }
    if (Buffer.byteLength(description, "utf8") > MAX_DESCRIPTION_BYTES) {
      return Promise.reject(new Error("Task description exceeds 10,000 bytes"));
    }

    const python = process.env.PYTHON_EXECUTABLE || "python3";
    const child = spawn(
      python,
      this.buildBridgeArguments(taskId, workspace),
      {
        cwd: TRUSTED_RUNTIME_CWD,
        detached: process.platform !== "win32",
        env: childEnvironment(),
        shell: false,
        stdio: ["pipe", "pipe", "pipe"],
      }
    );
    child.stdin.on("error", () => undefined);
    child.stdin.end(description);
    this.children.set(taskId, child);

    return new Promise((resolveResult, reject) => {
      let stdout = "";
      let stderr = "";
      let capturedBytes = 0;
      let forcedError: Error | null = null;
      const requestTermination = (): void => {
        void this.terminate(child).catch(() => {
          child.kill("SIGKILL");
        });
      };
      const configuredTimeoutMs = taskTimeoutMs();
      const timer = setTimeout(() => {
        forcedError = new Error(`Task exceeded the ${configuredTimeoutMs}ms server deadline`);
        requestTermination();
      }, configuredTimeoutMs);

      const append = (current: string, chunk: Buffer): string => {
        const remaining = Math.max(MAX_CAPTURE_BYTES - capturedBytes, 0);
        const accepted = chunk.subarray(0, remaining);
        capturedBytes += accepted.length;
        if (accepted.length < chunk.length) {
          forcedError = new Error("Python runner output exceeded the 1 MB safety limit");
          requestTermination();
        }
        return current + accepted.toString("utf8");
      };

      child.stdout.on("data", (chunk: Buffer) => {
        stdout = append(stdout, chunk);
      });
      child.stderr.on("data", (chunk: Buffer) => {
        stderr = append(stderr, chunk);
      });

      child.on("error", (error) => {
        clearTimeout(timer);
        this.children.delete(taskId);
        reject(error);
      });

      child.on("close", (code, signal) => {
        clearTimeout(timer);
        this.children.delete(taskId);
        if (forcedError) {
          reject(forcedError);
          return;
        }

        try {
          resolveResult(parseBridgeResult(stdout, taskId, code ?? -1, signal));
        } catch (error) {
          reject(new Error(`${error} (code=${code}, signal=${signal})`));
        }
      });
    });
  }

  private signalProcessGroup(child: ChildProcess, signal: NodeJS.Signals): void {
    if (process.platform !== "win32" && child.pid !== undefined) {
      try {
        process.kill(-child.pid, signal);
        return;
      } catch (error) {
        const code = (error as NodeJS.ErrnoException).code;
        if (code === "ESRCH") return;
        if (code !== "EPERM") throw error;
      }
    }
    if (child.exitCode === null && child.signalCode === null) {
      child.kill(signal);
    }
  }

  private async terminate(child: ChildProcess): Promise<void> {
    const existing = this.terminations.get(child);
    if (existing) return existing;
    const termination = this.terminateOnce(child).finally(() => {
      this.terminations.delete(child);
    });
    this.terminations.set(child, termination);
    return termination;
  }

  private async terminateOnce(child: ChildProcess): Promise<void> {
    const closed = new Promise<true>((resolveClosed) => {
      child.once("close", () => resolveClosed(true));
    });
    this.signalProcessGroup(child, "SIGTERM");
    let graceTimer: NodeJS.Timeout | undefined;
    const graceExpired = new Promise<false>((resolveGrace) => {
      graceTimer = setTimeout(() => resolveGrace(false), TERMINATION_GRACE_MS);
    });
    const closedDuringGrace = await Promise.race([closed, graceExpired]);
    if (graceTimer) clearTimeout(graceTimer);
    if (closedDuringGrace) return;
    this.signalProcessGroup(child, "SIGKILL");
    await closed;
  }

  async cancel(taskId: string): Promise<boolean> {
    const child = this.children.get(taskId);
    if (!child) return false;
    await this.terminate(child);
    return child.exitCode !== null || child.signalCode !== null;
  }
}

export const pythonTaskRunner = new PythonTaskRunner();
