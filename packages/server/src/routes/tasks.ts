import { Router, Request, Response } from "express";
import { v4 as uuidv4 } from "uuid";
import { z } from "zod";

const taskRouter = Router();

const CreateTaskSchema = z.object({
  description: z.string().min(1).max(10000),
  metadata: z.record(z.unknown()).optional(),
});

interface TaskRecord {
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

taskRouter.post("/", async (req: Request, res: Response) => {
  const parsed = CreateTaskSchema.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ error: "Invalid request", details: parsed.error.issues });
    return;
  }

  const task: TaskRecord = {
    id: uuidv4(),
    description: parsed.data.description,
    state: "submitted",
    result: null,
    error: null,
    metadata: parsed.data.metadata || {},
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  };

  tasks.set(task.id, task);

  // In production, this would dispatch to the Python agent system
  // via subprocess, message queue, or gRPC call
  console.log(`Task created: ${task.id} — ${task.description.slice(0, 80)}`);

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
  const task = tasks.get(id);
  if (!task) {
    res.status(404).json({ error: "Task not found" });
    return;
  }
  res.json(task);
});

taskRouter.delete("/:id", (req: Request, res: Response) => {
  const id = req.params.id as string;
  const task = tasks.get(id);
  if (!task) {
    res.status(404).json({ error: "Task not found" });
    return;
  }

  if (task.state === "submitted" || task.state === "completed" || task.state === "failed") {
    tasks.delete(id);
    res.json({ deleted: true, id });
  } else {
    res.status(409).json({ error: "Cannot delete task in state: " + task.state });
  }
});

taskRouter.post("/:id/cancel", (req: Request, res: Response) => {
  const id = req.params.id as string;
  const task = tasks.get(id);
  if (!task) {
    res.status(404).json({ error: "Task not found" });
    return;
  }

  if (task.state === "completed" || task.state === "failed" || task.state === "cancelled") {
    res.status(409).json({ error: "Task already in terminal state: " + task.state });
    return;
  }

  task.state = "cancelled";
  task.updated_at = new Date().toISOString();
  res.json(task);
});

export { taskRouter };
