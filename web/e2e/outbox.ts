import { readFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";

import { expect } from "@playwright/test";

/**
 * The emails the API "sent" during the browser tests.
 *
 * playwright.config.ts starts the API with no real sender and with
 * LEKA_EMAIL_OUTBOX_FILE pointing here: each message becomes one JSON line.
 * That is how these tests click the link a person would click, without an
 * inbox anywhere. The API refuses this variable in staging and production.
 */
export const OUTBOX = path.join(os.tmpdir(), "leka-e2e-outbox.jsonl");

type Sent = { to: string; subject: string; body: string; html: string | null };

function read(): Sent[] {
  try {
    return readFileSync(OUTBOX, "utf-8")
      .split("\n")
      .filter(Boolean)
      .map((line) => JSON.parse(line) as Sent);
  } catch {
    return [];
  }
}

/**
 * The link in the latest email to `to` whose subject is `subject`.
 *
 * Polled: emails leave after the response (and so after the commit), not
 * with it. Empty for ever means the API on :8000 was not started by
 * Playwright — a dev server reused from a terminal writes no outbox.
 */
export async function linkFromEmail(to: string, subject: string): Promise<URL> {
  let found: Sent | undefined;
  await expect
    .poll(
      () => {
        found = read()
          .filter((message) => message.to === to && message.subject === subject)
          .at(-1);
        return found !== undefined;
      },
      {
        message:
          `no "${subject}" email to ${to} in ${OUTBOX}. If an API was already ` +
          "running on :8000, Playwright reused it and it writes no outbox: stop it, or run with CI=1.",
      },
    )
    .toBe(true);

  const link = found!.body.match(/https?:\/\/\S+/)?.[0];
  expect(link, `no link in: ${found!.body}`).toBeTruthy();
  return new URL(link!);
}
