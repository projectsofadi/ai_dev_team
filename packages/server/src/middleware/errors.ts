import type { NextFunction, Request, Response } from "express";

type HttpError = Error & {
  status?: number;
  type?: string;
  body?: unknown;
};

export function classifyHttpError(error: Error & { status?: number }): {
  status: number;
  message: string;
} {
  const status = error.status;
  if (typeof status === "number" && status >= 400 && status < 500) {
    return {
      status,
      message:
        status === 413
          ? "Request body too large"
          : status === 403
            ? "Request origin is not allowed"
            : "Invalid request body",
    };
  }
  return { status: 500, message: "Internal server error" };
}

export function errorMiddleware(
  error: HttpError,
  req: Request,
  res: Response,
  _next: NextFunction
): void {
  const requestPath = req.originalUrl.split("?", 1)[0];
  if (
    /^\/a2a\/?$/.test(requestPath) &&
    error.status === 400 &&
    error.type === "entity.parse.failed"
  ) {
    res.status(400).json({
      jsonrpc: "2.0",
      id: null,
      error: { code: -32700, message: "Parse error" },
    });
    return;
  }

  const response = classifyHttpError(error);
  if (response.status === 500) {
    console.error("Unhandled server error:", error.name);
  }
  res.status(response.status).json({ error: response.message });
}
