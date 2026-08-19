/**
 * WebSocket handler for streaming agent output to clients.
 */

import { WebSocketServer, WebSocket } from "ws";
import { v4 as uuidv4 } from "uuid";
import { z } from "zod";

const WSMessageSchema = z.discriminatedUnion("type", [
  z.object({ type: z.literal("subscribe"), task_id: z.string().uuid() }),
  z.object({ type: z.literal("unsubscribe"), task_id: z.string().uuid() }),
  z.object({ type: z.literal("ping") }),
]);

type WSMessage = z.infer<typeof WSMessageSchema>;
type TaskLookup = (taskId: string) => unknown | undefined;

interface WSBroadcast {
  type: "task_update" | "agent_output" | "tool_call" | "error" | "pong";
  task_id?: string;
  data: unknown;
  timestamp: string;
}

const subscriptions = new Map<string, Set<WebSocket>>();
const clientSubscriptions = new WeakMap<WebSocket, Set<string>>();
const MAX_SUBSCRIPTIONS_PER_CLIENT = 32;

export function setupWebSocket(wss: WebSocketServer, lookupTask: TaskLookup): void {
  wss.on("connection", (ws: WebSocket) => {
    const clientId = uuidv4().slice(0, 8);
    clientSubscriptions.set(ws, new Set());
    console.log(`WebSocket client connected: ${clientId}`);

    ws.on("message", (raw: Buffer) => {
      try {
        const msg = WSMessageSchema.parse(JSON.parse(raw.toString()));
        handleMessage(ws, clientId, msg, lookupTask);
      } catch {
        sendError(ws, "Invalid WebSocket message");
      }
    });

    ws.on("close", () => {
      for (const [taskId, subs] of subscriptions) {
        subs.delete(ws);
        if (subs.size === 0) {
          subscriptions.delete(taskId);
        }
      }
      clientSubscriptions.delete(ws);
      console.log(`WebSocket client disconnected: ${clientId}`);
    });

    sendToClient(ws, {
      type: "pong",
      data: { clientId, message: "Connected to AI Dev Team" },
      timestamp: new Date().toISOString(),
    });
  });
}

function handleMessage(
  ws: WebSocket,
  clientId: string,
  msg: WSMessage,
  lookupTask: TaskLookup
): void {
  switch (msg.type) {
    case "subscribe": {
      const task = lookupTask(msg.task_id);
      if (!task) {
        sendError(ws, "Task not found", msg.task_id);
        return;
      }
      const clientTasks = clientSubscriptions.get(ws)!;
      if (!clientTasks.has(msg.task_id) && clientTasks.size >= MAX_SUBSCRIPTIONS_PER_CLIENT) {
        sendError(ws, "Subscription limit reached", msg.task_id);
        return;
      }
      if (!subscriptions.has(msg.task_id)) {
        subscriptions.set(msg.task_id, new Set());
      }
      subscriptions.get(msg.task_id)!.add(ws);
      clientTasks.add(msg.task_id);
      console.log(`Client ${clientId} subscribed to task ${msg.task_id}`);
      broadcastToClient(ws, msg.task_id, task);
      break;
    }

    case "unsubscribe": {
      const taskSubscriptions = subscriptions.get(msg.task_id);
      taskSubscriptions?.delete(ws);
      if (taskSubscriptions?.size === 0) {
        subscriptions.delete(msg.task_id);
      }
      clientSubscriptions.get(ws)?.delete(msg.task_id);
      break;
    }

    case "ping":
      sendToClient(ws, {
        type: "pong",
        data: { timestamp: Date.now() },
        timestamp: new Date().toISOString(),
      });
      break;
  }
}

function sendError(ws: WebSocket, message: string, taskId?: string): void {
  sendToClient(ws, {
    type: "error",
    task_id: taskId,
    data: { message },
    timestamp: new Date().toISOString(),
  });
}

function broadcastToClient(ws: WebSocket, taskId: string, data: unknown): void {
  sendToClient(ws, {
    type: "task_update",
    task_id: taskId,
    data,
    timestamp: new Date().toISOString(),
  });
}

function sendToClient(ws: WebSocket, message: WSBroadcast): void {
  if (ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify(message));
  }
}

export function broadcastTaskUpdate(taskId: string, data: unknown): void {
  const subs = subscriptions.get(taskId);
  if (!subs) return;

  for (const ws of subs) {
    broadcastToClient(ws, taskId, data);
  }
}

export function broadcastAgentOutput(
  taskId: string,
  agent: string,
  output: string
): void {
  const subs = subscriptions.get(taskId);
  if (!subs) return;

  const message: WSBroadcast = {
    type: "agent_output",
    task_id: taskId,
    data: { agent, output },
    timestamp: new Date().toISOString(),
  };

  for (const ws of subs) {
    sendToClient(ws, message);
  }
}
