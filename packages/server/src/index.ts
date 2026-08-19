import express from "express";
import { createServer, type IncomingMessage } from "http";
import cors from "cors";
import { WebSocketServer } from "ws";
import { getTaskById, taskRouter } from "./routes/tasks.js";
import { a2aRouter, agentCardHandler } from "./routes/a2a.js";
import {
  assertApiKeyConfigured,
  authMiddleware,
  isAuthorized,
} from "./middleware/auth.js";
import { tracingMiddleware } from "./middleware/tracing.js";
import { setupWebSocket } from "./ws/stream.js";
import { pythonTaskRunner } from "./task-runner.js";
import { errorMiddleware } from "./middleware/errors.js";

const PORT = parseInt(process.env.API_PORT || "8080", 10);
const HOST = process.env.API_HOST || "127.0.0.1";

assertApiKeyConfigured();
pythonTaskRunner.validateConfiguration();

const app = express();
const server = createServer(app);

const allowedOrigins = (process.env.CORS_ORIGINS || "")
  .split(",")
  .map((origin) => origin.trim())
  .filter(Boolean);
app.use(
  cors({
    origin(origin, callback) {
      if (!origin || allowedOrigins.includes(origin)) {
        callback(null, true);
        return;
      }
      callback(Object.assign(new Error("Origin is not allowed"), { status: 403 }));
    },
  })
);
app.get("/.well-known/agent-card.json", agentCardHandler);
app.use("/api", authMiddleware);
app.use("/a2a", authMiddleware);
app.use(express.json({ limit: "1mb" }));
app.use(tracingMiddleware);

app.get("/health", (_req, res) => {
  res.json({ status: "ok", service: "ai-dev-team", version: "0.1.0" });
});

app.use("/api/tasks", taskRouter);
app.use("/a2a", a2aRouter);

const wss = new WebSocketServer({
  server,
  path: "/ws",
  maxPayload: 16 * 1024,
  verifyClient: ({ req }: { req: IncomingMessage }) => {
    const origin = req.headers.origin;
    return (
      isAuthorized(req.headers) &&
      (!origin || allowedOrigins.includes(origin))
    );
  },
});
setupWebSocket(wss, getTaskById);

app.use(errorMiddleware);

server.listen(PORT, HOST, () => {
  console.log(`AI Dev Team API server running on http://${HOST}:${PORT}`);
  console.log(`WebSocket available at ws://${HOST}:${PORT}/ws`);
  console.log(`A2A endpoint at http://${HOST}:${PORT}/a2a`);
});

export { app, server };
