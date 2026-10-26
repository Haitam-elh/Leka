/**
 * The architect's installer, made in the browser (2026-10-25).
 *
 * What these protect: the .env it writes, model by model; nothing typed can
 * add a line — nor end the script's here-document and run a command; the
 * scripts bash reads parse; Windows' starts with a BOM; what is pasted holds
 * no comment (macOS' zsh runs « # … »).
 */

import { execFileSync } from "node:child_process";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

import { describe, expect, it } from "vitest";

import {
  EMPTY_SETUP,
  envText,
  given,
  installer,
  installerName,
  launcherName,
  MODELS,
  runCommand,
  type Setup,
} from "@/lib/architect-install";

const GEMINI: Setup = {
  confluenceUrl: "https://acme.atlassian.net",
  confluenceEmail: "ada@acme.example",
  confluenceToken: "jeton-secret",
  model: "gemini",
  modelName: MODELS.gemini.name,
  modelKey: "cle-secrete",
  modelUrl: MODELS.gemini.url,
};

function bashParses(script: string): void {
  const file = path.join(mkdtempSync(path.join(tmpdir(), "installer-")), "installer.sh");
  writeFileSync(file, script);
  execFileSync("bash", ["-n", file]);
}

describe("the architect's installer", () => {
  it("writes .env model by model — Copilot's without a model", () => {
    const env = envText(GEMINI);
    expect(env).toContain("CONFLUENCE_URL=https://acme.atlassian.net\n");
    expect(env).toContain("CONFLUENCE_TOKEN=jeton-secret\n");
    expect(env).toContain("ARCHITECT_LLM_PROVIDER=openai\n");
    expect(env).toContain("ARCHITECT_LLM_MODEL=gemini-3.8-flash\n");
    expect(env).toContain("ARCHITECT_LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai\n");
    expect(envText({ ...GEMINI, model: "azure", modelName: "gpt-41", modelUrl: "https://r.openai.azure.com" })).toContain(
      "ARCHITECT_LLM_PROVIDER=azure\nARCHITECT_LLM_MODEL=gpt-41\nARCHITECT_LLM_API_KEY=cle-secrete\nARCHITECT_LLM_BASE_URL=https://r.openai.azure.com\nARCHITECT_LLM_API_VERSION=2024-10-21",
    );
    expect(envText({ ...GEMINI, model: "anthropic", modelName: "claude-sonnet-5", modelUrl: "" })).toContain(
      "ARCHITECT_LLM_PROVIDER=anthropic",
    );
    const copilot = envText({ ...GEMINI, model: "copilot" });
    expect(copilot).not.toContain("ARCHITECT_LLM_");
    expect(copilot).toContain("CONFLUENCE_TOKEN=jeton-secret");
  });

  it("lets nothing typed add a line, nor end its here-document", () => {
    const tricked = { ...GEMINI, confluenceToken: "x\nLEKA_ENV_FIN\nrm -rf ~\n" };
    const env = envText(tricked);
    expect(env).toContain("CONFLUENCE_TOKEN=x LEKA_ENV_FIN rm -rf ~\n");
    expect(env.split("\n").filter((line) => line === "LEKA_ENV_FIN")).toEqual([]);
    const script = installer("macos", tricked);
    // One line ends the here-document: its own.
    expect(script.split("\n").filter((line) => line === "LEKA_ENV_FIN")).toHaveLength(1);
    bashParses(script);
  });

  it("macOS' and Linux' installers parse, with what was typed or without", () => {
    for (const system of ["macos", "linux"] as const) {
      const made = installer(system, GEMINI);
      expect(made.startsWith("#!/usr/bin/env bash\n")).toBe(true);
      expect(made).toContain("cat > .env <<'LEKA_ENV_FIN'\n# L'Architecte applicatif");
      expect(made).toContain("ARCHITECT_LLM_API_KEY=cle-secrete");
      expect(made).toContain(`LANCEUR="${launcherName(system)}"`);
      expect(made).toContain('rm -f -- "$SOI"');
      bashParses(made);
      const bare = installer(system, EMPTY_SETUP);
      expect(given(EMPTY_SETUP)).toBe(false);
      expect(bare).not.toContain("LEKA_ENV_FIN");
      expect(bare).toContain("[ -f .env ] || cp leka-architect/.env.example .env");
      bashParses(bare);
    }
    expect(installer("macos", EMPTY_SETUP)).toContain("open -e .env");
  });

  it("Windows': PowerShell, a BOM first, its details in a here-string", () => {
    const made = installer("windows", GEMINI);
    expect(made.charCodeAt(0)).toBe(0xfeff);
    expect(made).toContain("$Configuration = @'\n# L'Architecte applicatif");
    expect(made).toContain("ARCHITECT_LLM_API_KEY=cle-secrete\nARCHITECT_LLM_BASE_URL=https://generativelanguage");
    expect(made).toContain("'@\nSet-Content -Path (Join-Path $Dossier \".env\")");
    expect(made).toContain("Lancer l'architecte.bat");
    expect(made).toContain("Remove-Item -Force $Soi");
    expect(installerName("windows")).toBe("installer-architecte.ps1");
  });

  it("is run by one line, with no comment in it", () => {
    for (const system of ["windows", "macos", "linux"] as const) {
      expect(runCommand(system)).not.toMatch(/(^|\s)#/);
      expect(runCommand(system)).toContain("installer-architecte");
    }
    expect(runCommand("macos")).toBe('bash "$(ls -t ~/Downloads/installer-architecte*.sh | head -1)"');
  });
});
