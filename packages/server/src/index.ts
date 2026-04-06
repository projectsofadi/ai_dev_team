import express from "express";
import { createServer } from "http";
import cors from "cors";
import { WebSocketServer } from "ws";
import { taskRouter } from "./routes/tasks.js";
import { a2aRouter } from "./routes/a2a.js";
import { authMiddleware } from "./middleware/auth.js";
import { tracingMiddleware } from "./middleware/tracing.js";
import { setupWebSocket } from "./ws/stream.js";

const PORT = parseInt(process.env.API_PORT || "8080", 10);
const HOST = process.env.API_HOST || "0.0.0.0";

const app = express();
const server = createServer(app);

app.use(cors());
app.use(express.json({ limit: "10mb" }));
app.use(tracingMiddleware);

app.get("/health", (_req, res) => {
  res.json({ status: "ok", service: "ai-dev-team", version: "0.1.0" });
});

app.use("/api", authMiddleware);
app.use("/api/tasks", taskRouter);
app.use("/a2a", a2aRouter);

const wss = new WebSocketServer({ server, path: "/ws" });
setupWebSocket(wss);

app.use(
  (
    err: Error,
    _req: express.Request,
    res: express.Response,
    _next: express.NextFunction
  ) => {
    console.error("Unhandled error:", err);
    res.status(500).json({ error: "Internal server error" });
  }
);

server.listen(PORT, HOST, () => {
  console.log(`AI Dev Team API server running on http://${HOST}:${PORT}`);
  console.log(`WebSocket available at ws://${HOST}:${PORT}/ws`);
  console.log(`A2A endpoint at http://${HOST}:${PORT}/a2a`);
});

export { app, server };
