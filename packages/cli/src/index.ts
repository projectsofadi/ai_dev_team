#!/usr/bin/env node

import { Command } from "commander";
import { ReportedCliError, runCommand } from "./commands/run.js";
import { statusCommand } from "./commands/status.js";
import { configCommand } from "./commands/config.js";

const program = new Command();

program
  .name("ai-dev-team")
  .description("CLI for the AI Dev Team multi-agent system")
  .version("0.1.0");

program.addCommand(runCommand);
program.addCommand(statusCommand);
program.addCommand(configCommand);

program.parseAsync().catch((error: unknown) => {
  if (error instanceof Error && !(error instanceof ReportedCliError)) {
    console.error(error.message);
  }
  process.exitCode = 1;
});
