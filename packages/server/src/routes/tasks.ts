import { Router, Request, Response } from "express";
import { v4 as uuidv4 } from "uuid";
import { z } from "zod";
import { pythonTaskRunner } from "../task-runner.js";
import { broadcastTaskUpdate } from "../ws/stream.js";

const taskRouter = Router();

const CreateTaskSchema = z.object({
  description: z
    .string()
    .min(1)
    .max(10000)
    .refine((value) => Buffer.byteLength(value, "utf8") <= 10_000, {
      message: "Description must not exceed 10,000 UTF-8 bytes",
    }),
  metadata: z.record(z.unknown()).optional(),
});

export interface TaskRecord {
  id: string;
  description: string;
  state: string;
  result: string | null;
  error: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

const tasks = new Map<string, TaskRecord>();

function updateTask(
  task: TaskRecord,
  state: string,
  result: string | null = task.result,
  error: string | null = task.error
): void {
  if (task.state === "cancelling" || task.state === "cancelled") return;
  task.state = state;
  task.result = result;
  task.error = error;
  task.updated_at = new Date().toISOString();
  broadcastTaskUpdate(task.id, task);
}

async function dispatchTask(task: TaskRecord): Promise<void> {
  if (task.state !== "submitted") return;
  updateTask(task, "executing");
  try {
    const outcome = await pythonTaskRunner.run(task.id, task.description);
    updateTask(task, outcome.state, outcome.result, outcome.error);
  } catch (error) {
    updateTask(task, "failed", null, error instanceof Error ? error.message : String(error));
  }
}

export function submitTask(
  description: string,
  metadata: Record<string, unknown> = {}
): TaskRecord {
  const now = new Date().toISOString();
  const task: TaskRecord = {
    id: uuidv4(),
    description,
    state: "submitted",
    result: null,
    error: null,
    metadata,
    created_at: now,
    updated_at: now,
  };
  tasks.set(task.id, task);
  queueMicrotask(() => void dispatchTask(task));
  return task;
}

export function getTaskById(id: string): TaskRecord | undefined {
  return tasks.get(id);
}

export async function cancelTaskById(id: string): Promise<TaskRecord | undefined> {
  const task = tasks.get(id);
  if (!task) return undefined;
  if (["completed", "failed", "cancelled", "cancelling"].includes(task.state)) return task;

  const wasSubmitted = task.state === "submitted";
  task.state = "cancelling";
  task.updated_at = new Date().toISOString();
  broadcastTaskUpdate(task.id, task);

  const processStopped = await pythonTaskRunner.cancel(task.id);
  if (processStopped || wasSubmitted) {
    task.state = "cancelled";
  } else {
    task.state = "failed";
    task.error = "Cancellation could not confirm that the worker stopped";
  }
  task.updated_at = new Date().toISOString();
  broadcastTaskUpdate(task.id, task);
  return task;
}

taskRouter.post("/", async (req: Request, res: Response) => {
  const parsed = CreateTaskSchema.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ error: "Invalid request", details: parsed.error.issues });
    return;
  }

  const task = submitTask(parsed.data.description, parsed.data.metadata || {});
  res.status(201).json(task);
});

taskRouter.get("/", (_req: Request, res: Response) => {
  const allTasks = Array.from(tasks.values()).sort(
    (a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime()
  );
  res.json({ tasks: allTasks, total: allTasks.length });
});

taskRouter.get("/:id", (req: Request, res: Response) => {
  const id = req.params.id as string;
  const task = getTaskById(id);
  if (!task) {
    res.status(404).json({ error: "Task not found" });
    return;
  }
  res.json(task);
});

taskRouter.delete("/:id", (req: Request, res: Response) => {
  const id = req.params.id as string;
  const task = getTaskById(id);
  if (!task) {
    res.status(404).json({ error: "Task not found" });
    return;
  }

  if (["completed", "failed", "cancelled"].includes(task.state)) {
    tasks.delete(id);
    res.json({ deleted: true, id });
  } else {
    res.status(409).json({ error: "Cannot delete task in state: " + task.state });
  }
});

taskRouter.post("/:id/cancel", async (req: Request, res: Response) => {
  const id = req.params.id as string;
  const task = getTaskById(id);
  if (!task) {
    res.status(404).json({ error: "Task not found" });
    return;
  }

  if (["completed", "failed", "cancelled", "cancelling"].includes(task.state)) {
    res.status(409).json({ error: "Task already in terminal state: " + task.state });
    return;
  }

  res.json(await cancelTaskById(id));
});

export { taskRouter };
