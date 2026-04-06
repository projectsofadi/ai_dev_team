/**
 * WebSocket handler for streaming agent output to clients.
 */

import { WebSocketServer, WebSocket } from "ws";
import { v4 as uuidv4 } from "uuid";

interface WSMessage {
  type: "subscribe" | "unsubscribe" | "ping";
  task_id?: string;
}

interface WSBroadcast {
  type: "task_update" | "agent_output" | "tool_call" | "error" | "pong";
  task_id?: string;
  data: unknown;
  timestamp: string;
}

const subscriptions = new Map<string, Set<WebSocket>>();

export function setupWebSocket(wss: WebSocketServer): void {
  wss.on("connection", (ws: WebSocket) => {
    const clientId = uuidv4().slice(0, 8);
    console.log(`WebSocket client connected: ${clientId}`);

    ws.on("message", (raw: Buffer) => {
      try {
        const msg: WSMessage = JSON.parse(raw.toString());
        handleMessage(ws, clientId, msg);
      } catch {
        sendToClient(ws, {
          type: "error",
          data: { message: "Invalid JSON message" },
          timestamp: new Date().toISOString(),
        });
      }
    });

    ws.on("close", () => {
      for (const [taskId, subs] of subscriptions) {
        subs.delete(ws);
        if (subs.size === 0) {
          subscriptions.delete(taskId);
        }
      }
      console.log(`WebSocket client disconnected: ${clientId}`);
    });

    sendToClient(ws, {
      type: "pong",
      data: { clientId, message: "Connected to AI Dev Team" },
      timestamp: new Date().toISOString(),
    });
  });
}

function handleMessage(ws: WebSocket, clientId: string, msg: WSMessage): void {
  switch (msg.type) {
    case "subscribe":
      if (msg.task_id) {
        if (!subscriptions.has(msg.task_id)) {
          subscriptions.set(msg.task_id, new Set());
        }
        subscriptions.get(msg.task_id)!.add(ws);
        console.log(`Client ${clientId} subscribed to task ${msg.task_id}`);
      }
      break;

    case "unsubscribe":
      if (msg.task_id) {
        subscriptions.get(msg.task_id)?.delete(ws);
      }
      break;

    case "ping":
      sendToClient(ws, {
        type: "pong",
        data: { timestamp: Date.now() },
        timestamp: new Date().toISOString(),
      });
      break;
  }
}

function sendToClient(ws: WebSocket, message: WSBroadcast): void {
  if (ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify(message));
  }
}

export function broadcastTaskUpdate(taskId: string, data: unknown): void {
  const subs = subscriptions.get(taskId);
  if (!subs) return;

  const message: WSBroadcast = {
    type: "task_update",
    task_id: taskId,
    data,
    timestamp: new Date().toISOString(),
  };

  for (const ws of subs) {
    sendToClient(ws, message);
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
