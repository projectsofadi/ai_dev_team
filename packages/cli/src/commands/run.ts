import { Command } from "commander";
import chalk from "chalk";
import ora from "ora";
import { WebSocket } from "ws";

const DEFAULT_API = "http://localhost:8080";

export const runCommand = new Command("run")
  .description("Submit a development task to the AI dev team")
  .argument("<description>", "Task description")
  .option("-s, --server <url>", "API server URL", DEFAULT_API)
  .option("-k, --api-key <key>", "API key for authentication")
  .option("-w, --watch", "Watch task progress via WebSocket", false)
  .action(async (description: string, opts) => {
    const spinner = ora("Submitting task...").start();

    try {
      const headers: Record<string, string> = {
        "Content-Type": "application/json",
      };
      if (opts.apiKey) {
        headers["Authorization"] = `Bearer ${opts.apiKey}`;
      }

      const res = await fetch(`${opts.server}/api/tasks`, {
        method: "POST",
        headers,
        body: JSON.stringify({ description }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ error: res.statusText }));
        spinner.fail(chalk.red(`Failed: ${(err as Record<string, string>).error}`));
        process.exit(1);
      }

      const task = (await res.json()) as Record<string, string>;
      spinner.succeed(chalk.green(`Task created: ${task.id}`));

      console.log(chalk.dim(`  Description: ${description.slice(0, 100)}`));
      console.log(chalk.dim(`  State: ${task.state}`));

      if (opts.watch) {
        await watchTask(opts.server, task.id);
      }
    } catch (err) {
      spinner.fail(chalk.red(`Error: ${err}`));
      process.exit(1);
    }
  });

async function watchTask(serverUrl: string, taskId: string): Promise<void> {
  const wsUrl = serverUrl.replace(/^http/, "ws") + "/ws";
  console.log(chalk.dim(`\nConnecting to ${wsUrl}...`));

  return new Promise((resolve, reject) => {
    const ws = new WebSocket(wsUrl);

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
            if (
              data.state === "completed" ||
              data.state === "failed" ||
              data.state === "cancelled"
            ) {
              ws.close();
              resolve();
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
            console.log(chalk.red(`Error: ${data.message}`));
            break;
          }
        }
      } catch {
        // ignore parse errors
      }
    });

    ws.on("close", () => {
      console.log(chalk.dim("\nDisconnected."));
      resolve();
    });

    ws.on("error", (err: Error) => {
      console.error(chalk.red(`WebSocket error: ${err.message}`));
      reject(err);
    });
  });
}
