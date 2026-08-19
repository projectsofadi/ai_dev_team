import { spawn } from "node:child_process";
import { writeFileSync } from "node:fs";

const [mode, taskId, pidFile] = process.argv.slice(2);

process.stdin.resume();
process.stdin.on("end", () => {
  if (mode === "success") {
    console.log(
      `AI_DEV_TEAM_RESULT=${JSON.stringify({
        id: taskId,
        state: "completed",
        result: "fixture complete",
        error: null,
      })}`
    );
    return;
  }
  if (mode === "completed-exit-one") {
    console.log(
      `AI_DEV_TEAM_RESULT=${JSON.stringify({
        id: taskId,
        state: "completed",
        result: "must not be accepted",
        error: null,
      })}`
    );
    process.exitCode = 1;
    return;
  }
  if (mode === "malformed") {
    console.log('AI_DEV_TEAM_RESULT={"private":"BRIDGE-SECRET-MARKER"');
    process.exitCode = 1;
    return;
  }
  if (mode === "flood") {
    process.stdout.write("x".repeat(1_100_000));
    setInterval(() => undefined, 1_000);
    return;
  }
  if (mode === "tree") {
    const grandchild = spawn(process.execPath, ["-e", "setInterval(() => {}, 1000)"], {
      stdio: "inherit",
    });
    if (grandchild.pid === undefined) {
      throw new Error("tree fixture could not start its grandchild");
    }
    if (pidFile) {
      writeFileSync(pidFile, String(grandchild.pid), { encoding: "utf8" });
    }
    setInterval(() => undefined, 1_000);
    return;
  }
  process.exitCode = 2;
});
