/**
 * Request tracing middleware — adds trace IDs and logs request timing.
 */

import { Request, Response, NextFunction } from "express";
import { v4 as uuidv4 } from "uuid";

export function tracingMiddleware(
  req: Request,
  res: Response,
  next: NextFunction
): void {
  const traceId = (req.headers["x-trace-id"] as string) || uuidv4();
  const start = Date.now();

  res.setHeader("x-trace-id", traceId);

  res.on("finish", () => {
    const duration = Date.now() - start;
    console.log(
      JSON.stringify({
        trace_id: traceId,
        method: req.method,
        path: req.path,
        status: res.statusCode,
        duration_ms: duration,
        timestamp: new Date().toISOString(),
      })
    );
  });

  next();
}
