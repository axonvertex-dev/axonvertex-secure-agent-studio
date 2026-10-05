import { createHash } from "node:crypto";

export function sha256Json(value: unknown): string {
  const canonical = JSON.stringify(value);
  return `sha256:${createHash("sha256").update(canonical).digest("hex")}`;
}
