import { execFileSync } from "node:child_process";
import path from "node:path";

import { pythonExecutable, repositoryRoot } from "./python";
import { DEMO_EMAIL } from "./sign-in";

/**
 * The demo account's language, set as the database holds it — and its
 * region cleared — for the specs that change them, to give French back
 * whatever happened (docs/languages.md).
 */
export function accountLanguage(language: string | null): void {
  execFileSync(
    pythonExecutable(),
    [
      "-c",
      [
        "import asyncio, sys",
        "from sqlalchemy import update",
        "from leka.db import session_factory, system_scope",
        "from leka.identity import User",
        "async def main(email, language):",
        "    with system_scope():",
        "        async with session_factory() as session:",
        "            await session.execute(update(User).where(User.email == email).values(language=language, region=None))",
        "            await session.commit()",
        "asyncio.run(main(sys.argv[1], sys.argv[2] or None))",
      ].join("\n"),
      DEMO_EMAIL,
      language ?? "",
    ],
    { cwd: path.join(repositoryRoot(), "api"), stdio: "inherit" },
  );
}

