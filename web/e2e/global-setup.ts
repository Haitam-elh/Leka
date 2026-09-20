import { execFileSync } from "node:child_process";
import path from "node:path";

import { pythonExecutable, repositoryRoot } from "./python";

/**
 * Put the demo data in place, and forget throttling counters, before the
 * browser tests run.
 *
 * The seed: without it `npm run e2e` passes only if someone happened to run
 * it by hand first, which is the definition of a test that works on one
 * machine. It is idempotent, so running it every time costs a second.
 *
 * The rate limits: they are real state in Redis and they survive between
 * runs. Running the suite three times in a row exhausted the hourly
 * allowance for password resets and the fourth run failed — the throttling
 * doing exactly its job, against us. Clearing here keeps the suite
 * repeatable without weakening the limits, which have their own tests.
 */
export default function globalSetup() {
  const root = repositoryRoot();
  const python = pythonExecutable();

  execFileSync(python, [path.join(root, "scripts", "seed.py")], {
    cwd: root,
    stdio: "inherit",
  });

  execFileSync(
    python,
    [
      "-c",
      [
        "import asyncio, redis.asyncio as redis",
        "from leka.core.config import settings",
        "async def clear():",
        "    client = redis.from_url(str(settings.redis_url))",
        "    keys = [k async for k in client.scan_iter('leka:ratelimit:*')]",
        "    if keys: await client.delete(*keys)",
        "    await client.aclose()",
        "asyncio.run(clear())",
      ].join("\n"),
    ],
    { cwd: path.join(root, "api"), stdio: "inherit" },
  );
}
