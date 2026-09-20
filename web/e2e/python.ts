import { existsSync } from "node:fs";
import path from "node:path";

/**
 * Which Python runs the API and the seed.
 *
 * Locally that is the virtualenv in api/. On a CI runner there is no
 * virtualenv — dependencies are installed into the runner's own Python — so
 * LEKA_PYTHON overrides it. Without this indirection the config works on one
 * of the two and silently not the other.
 */
export function pythonExecutable(): string {
  const override = process.env.LEKA_PYTHON;
  if (override) return override;

  const venv = path.resolve(__dirname, "..", "..", "api", ".venv", "bin", "python");
  if (existsSync(venv)) return venv;

  return "python";
}

export function repositoryRoot(): string {
  return path.resolve(__dirname, "..", "..");
}
