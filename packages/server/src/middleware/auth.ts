/**
 * API key authentication middleware.
 */

import { Request, Response, NextFunction } from "express";
import { timingSafeEqual } from "node:crypto";
import type { IncomingHttpHeaders } from "node:http";

function configuredApiKey(): string {
  return process.env.API_KEY || "";
}

export function assertApiKeyConfigured(): void {
  const apiKey = configuredApiKey();
  if (!apiKey || apiKey === "your-api-key-here") {
    throw new Error("API_KEY must be set to a non-placeholder value");
  }
}

function firstHeader(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

function providedApiKey(headers: IncomingHttpHeaders): string | undefined {
  const authorization = firstHeader(headers.authorization);
  if (authorization?.startsWith("Bearer ")) {
    return authorization.slice("Bearer ".length);
  }
  return firstHeader(headers["x-api-key"]);
}

export function isAuthorized(headers: IncomingHttpHeaders): boolean {
  const apiKey = configuredApiKey();
  if (!apiKey) return false;
  const provided = providedApiKey(headers);
  if (!provided) return false;

  const expectedBuffer = Buffer.from(apiKey);
  const providedBuffer = Buffer.from(provided);
  return (
    expectedBuffer.length === providedBuffer.length &&
    timingSafeEqual(expectedBuffer, providedBuffer)
  );
}

export function authMiddleware(
  req: Request,
  res: Response,
  next: NextFunction
): void {
  if (!isAuthorized(req.headers)) {
    res.status(401).json({ error: "Unauthorized: invalid or missing API key" });
    return;
  }

  next();
}
