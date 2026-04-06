import { Command } from "commander";
import chalk from "chalk";
import { readFileSync, existsSync } from "fs";
import { resolve } from "path";

export const configCommand = new Command("config")
  .description("View or manage configuration")
  .option("-e, --env-file <path>", "Path to .env file", ".env")
  .action((opts) => {
    const envPath = resolve(opts.envFile);

    console.log(chalk.bold("AI Dev Team Configuration\n"));

    if (existsSync(envPath)) {
      console.log(chalk.dim(`Reading from: ${envPath}\n`));
      const content = readFileSync(envPath, "utf-8");
      const lines = content.split("\n").filter((l) => l.trim() && !l.startsWith("#"));

      for (const line of lines) {
        const [key, ...valueParts] = line.split("=");
        const value = valueParts.join("=");

        if (
          key.toLowerCase().includes("key") ||
          key.toLowerCase().includes("secret") ||
          key.toLowerCase().includes("password")
        ) {
          console.log(`  ${chalk.cyan(key)} = ${chalk.dim("****")}`);
        } else {
          console.log(`  ${chalk.cyan(key)} = ${value}`);
        }
      }
    } else {
      console.log(chalk.yellow(`No .env file found at ${envPath}`));
      console.log(chalk.dim("\nCopy .env.example to .env and fill in your values:"));
      console.log(chalk.dim("  cp .env.example .env"));
    }

    console.log(chalk.dim("\nEnvironment overrides:"));
    const envVars = [
      "OPENAI_API_KEY",
      "ANTHROPIC_API_KEY",
      "DEFAULT_PROVIDER",
      "DEFAULT_MODEL",
      "API_PORT",
      "LOG_LEVEL",
    ];

    for (const key of envVars) {
      const val = process.env[key];
      if (val) {
        const display = key.includes("KEY") ? "****" : val;
        console.log(`  ${chalk.green("✓")} ${key} = ${display}`);
      } else {
        console.log(`  ${chalk.dim("○")} ${key} ${chalk.dim("(not set)")}`);
      }
    }
  });
