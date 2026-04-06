/**
 * API key authentication middleware.
 */

import { Request, Response, NextFunction } from "express";

const API_KEY = process.env.API_KEY || "";

export function authMiddleware(
  req: Request,
  res: Response,
  next: NextFunction
): void {
  if (!API_KEY) {
    next();
    return;
  }

  const provided =
    req.headers.authorization?.replace("Bearer ", "") ||
    (req.headers["x-api-key"] as string);

  if (!provided || provided !== API_KEY) {
    res.status(401).json({ error: "Unauthorized: invalid or missing API key" });
    return;
  }

  next();
}
