import { Command } from "commander";
import chalk from "chalk";

const DEFAULT_API = "http://localhost:8080";

export const statusCommand = new Command("status")
  .description("Check the status of a task or list all tasks")
  .argument("[task-id]", "Task ID to check (omit to list all)")
  .option("-s, --server <url>", "API server URL", DEFAULT_API)
  .option("-k, --api-key <key>", "API key (prefer AI_DEV_TEAM_API_KEY env)")
  .action(async (taskId: string | undefined, opts) => {
    const apiKey = opts.apiKey || process.env.AI_DEV_TEAM_API_KEY;
    if (!apiKey) {
      throw new Error("Set AI_DEV_TEAM_API_KEY before using the CLI");
    }
    const headers: Record<string, string> = {
      Authorization: `Bearer ${apiKey}`,
    };

    try {
      if (taskId) {
        const res = await fetch(`${opts.server}/api/tasks/${taskId}`, {
          headers,
        });

        if (!res.ok) {
          throw new Error(`Task request failed (${res.status}): ${taskId}`);
        }

        const task = (await res.json()) as Record<string, unknown>;
        printTask(task);
      } else {
        const res = await fetch(`${opts.server}/api/tasks`, { headers });

        if (!res.ok) {
          throw new Error(`Failed to fetch tasks (${res.status})`);
        }

        const data = (await res.json()) as {
          tasks: Array<Record<string, unknown>>;
          total: number;
        };

        if (data.tasks.length === 0) {
          console.log(chalk.dim("No tasks found."));
          return;
        }

        console.log(chalk.bold(`Tasks (${data.total}):\n`));
        for (const task of data.tasks) {
          printTaskSummary(task);
        }
      }
    } catch (err) {
      console.error(chalk.red(`Error: ${err}`));
      throw err;
    }
  });

function printTask(task: Record<string, unknown>): void {
  const stateColor = getStateColor(task.state as string);
  console.log(chalk.bold(`Task: ${task.id}`));
  console.log(`  State:       ${stateColor(task.state as string)}`);
  console.log(`  Description: ${task.description}`);
  console.log(`  Created:     ${task.created_at}`);
  console.log(`  Updated:     ${task.updated_at}`);
  if (task.result) {
    console.log(`  Result:      ${task.result}`);
  }
  if (task.error) {
    console.log(chalk.red(`  Error:       ${task.error}`));
  }
}

function printTaskSummary(task: Record<string, unknown>): void {
  const stateColor = getStateColor(task.state as string);
  const desc = (task.description as string).slice(0, 60);
  console.log(
    `  ${chalk.dim((task.id as string).slice(0, 8))}  ${stateColor(
      (task.state as string).padEnd(12)
    )}  ${desc}`
  );
}

function getStateColor(state: string): (s: string) => string {
  switch (state) {
    case "completed":
      return chalk.green;
    case "failed":
      return chalk.red;
    case "cancelled":
      return chalk.gray;
    case "executing":
    case "planning":
      return chalk.yellow;
    default:
      return chalk.blue;
  }
}
