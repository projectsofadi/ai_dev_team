import { Command } from "commander";
import chalk from "chalk";
import ora from "ora";
import { WebSocket } from "ws";

const DEFAULT_API = "http://localhost:8080";

export class ReportedCliError extends Error {
  override readonly name = "ReportedCliError";
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export const runCommand = new Command("run")
  .description("Submit a development task to the AI dev team")
  .argument("<description>", "Task description")
  .option("-s, --server <url>", "API server URL", DEFAULT_API)
  .option("-k, --api-key <key>", "API key (prefer AI_DEV_TEAM_API_KEY env)")
  .option("-w, --watch", "Watch task progress via WebSocket", false)
  .action(async (description: string, opts) => {
    const spinner = ora("Submitting task...").start();
    const apiKey = opts.apiKey || process.env.AI_DEV_TEAM_API_KEY;

    try {
      if (!apiKey) {
        throw new Error("Set AI_DEV_TEAM_API_KEY before using the CLI");
      }
      const headers: Record<string, string> = {
        "Content-Type": "application/json",
        Authorization: `Bearer ${apiKey}`,
      };

      const res = await fetch(`${opts.server}/api/tasks`, {
        method: "POST",
        headers,
        body: JSON.stringify({ description }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ error: res.statusText }));
        throw new Error((err as Record<string, string>).error || res.statusText);
      }

      const task = (await res.json()) as Record<string, string>;
      spinner.succeed(chalk.green(`Task created: ${task.id}`));

      console.log(chalk.dim(`  Description: ${description.slice(0, 100)}`));
      console.log(chalk.dim(`  State: ${task.state}`));

      if (opts.watch) {
        await watchTask(opts.server, task.id, apiKey);
      }
    } catch (err) {
      const message = errorMessage(err);
      spinner.fail(chalk.red(`Error: ${message}`));
      throw new ReportedCliError(message, { cause: err });
    }
  });

export function terminalTaskError(state: string, detail?: string): Error | null {
  if (state === "completed") return null;
  if (state === "failed" || state === "cancelled") {
    return new Error(detail || `Task ended in state: ${state}`);
  }
  return null;
}

async function watchTask(
  serverUrl: string,
  taskId: string,
  apiKey: string
): Promise<void> {
  const wsUrl = serverUrl.replace(/^http/, "ws") + "/ws";
  console.log(chalk.dim(`\nConnecting to ${wsUrl}...`));

  return new Promise((resolve, reject) => {
    let terminalUpdateReceived = false;
    const ws = new WebSocket(wsUrl, {
      headers: { Authorization: `Bearer ${apiKey}` },
    });
    const timeout = setTimeout(() => {
      ws.close();
      reject(new Error("Timed out waiting for a terminal task update"));
    }, 10 * 60 * 1000);

    ws.on("open", () => {
      console.log(chalk.green("Connected. Watching task progress...\n"));
      ws.send(JSON.stringify({ type: "subscribe", task_id: taskId }));
    });

    ws.on("message", (raw: Buffer) => {
      try {
        const msg = JSON.parse(raw.toString()) as Record<string, unknown>;

        switch (msg.type) {
          case "task_update": {
            const data = msg.data as Record<string, string>;
            console.log(chalk.blue(`[${msg.timestamp}] State: ${data.state}`));
            if (["completed", "failed", "cancelled"].includes(data.state)) {
              terminalUpdateReceived = true;
              clearTimeout(timeout);
              ws.close();
              const terminalError = terminalTaskError(data.state, data.error);
              if (terminalError) reject(terminalError);
              else resolve();
            }
            break;
          }
          case "agent_output": {
            const data = msg.data as Record<string, string>;
            console.log(chalk.yellow(`[${data.agent}] ${data.output}`));
            break;
          }
          case "error": {
            const data = msg.data as Record<string, string>;
            clearTimeout(timeout);
            ws.close();
            reject(new Error(data.message || "WebSocket task subscription failed"));
            break;
          }
        }
      } catch {
        // ignore parse errors
      }
    });

    ws.on("close", () => {
      clearTimeout(timeout);
      console.log(chalk.dim("\nDisconnected."));
      if (!terminalUpdateReceived) {
        reject(new Error("WebSocket closed before a terminal task update"));
      }
    });

    ws.on("error", (err: Error) => {
      clearTimeout(timeout);
      reject(err);
    });
  });
}
