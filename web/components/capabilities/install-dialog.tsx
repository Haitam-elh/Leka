"use client";

import { Check, Copy, Download, PackageOpen } from "lucide-react";
import { useState } from "react";

import { Button, buttonVariants } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Tabs, TabsList, TabsPanel, TabsTab } from "@/components/ui/tabs";
import { apiAddress } from "@/lib/api";
import { useDictionary } from "@/lib/i18n/locale-provider";

/**
 * « Installer dans votre environnement » (2026-10-25): the architect on the
 * organisation's own machines, its own model, its own Confluence — nothing
 * through LEKA. Three ways: a terminal, an MCP client (Copilot in VS Code,
 * Claude, Cursor), a model without tools (the prompt pack). Each its
 * download — authenticated, refused to an organisation the agent is not
 * dedicated to (GET /capabilities/{key}/package) — and its commands, to
 * copy: Windows', macOS' or Linux's (2026-10-25), this browser's first.
 */

/** The agents a customer may install: their package is built from LEKA's own code. */
export const INSTALLABLE: ReadonlySet<string> = new Set(["application-architecture"]);

/** Where it is installed: the commands differ (2026-10-25: Windows, macOS, Linux). */
type System = "windows" | "macos" | "linux";
const SYSTEMS: readonly System[] = ["windows", "macos", "linux"];

/** The system of this browser — a guess, changed in one click. */
function systemOf(agent: string): System {
  if (/Windows/i.test(agent)) return "windows";
  if (/Mac|darwin/i.test(agent)) return "macos";
  return "linux";
}

/** Its own installation, in a folder of its own: a virtual environment, nothing
 * system-wide, no administrator rights. */
const INSTALL: Record<System, string> = {
  windows: `# PowerShell, dans le dossier où le paquet est dézippé — Python 3.10+ (python.org)
py -3 -m venv .venv
.venv\\Scripts\\python -m pip install .\\leka-architect
Copy-Item leka-architect\\.env.example .env
notepad .env      # Confluence et votre modèle
.venv\\Scripts\\leka-architect spaces`,
  macos: `# Terminal, dans le dossier où le paquet est dézippé — Python 3.10+ (brew install python@3.12)
python3 -m venv .venv
.venv/bin/pip install ./leka-architect
cp leka-architect/.env.example .env && open -e .env      # Confluence et votre modèle
.venv/bin/leka-architect spaces`,
  linux: `# Dans le dossier où le paquet est dézippé — Python 3.10+ (sudo apt install python3-venv)
python3 -m venv .venv
.venv/bin/pip install ./leka-architect
cp leka-architect/.env.example .env && nano .env      # Confluence et votre modèle
.venv/bin/leka-architect spaces`,
};

const BIN: Record<System, string> = {
  windows: ".venv\\Scripts\\leka-architect",
  macos: ".venv/bin/leka-architect",
  linux: ".venv/bin/leka-architect",
};

function run(system: System): string {
  const bin = BIN[system];
  return `${bin} deck --space MO --parcours "Paiement CB" --perimetre "Digital - Espace Client" --output rapport
${bin} simulate --space ARCHI --output rapport`;
}

const DOCKER = `docker build -t leka-architect ./leka-architect
docker run --rm --env-file .env -v "$PWD/rapport:/travail/rapport" leka-architect deck --space MO --parcours "Paiement CB" --perimetre "Digital" --output rapport`;

/** Copilot in VS Code: the .venv of the folder opened, its .env. */
function vscode(system: System): string {
  const command =
    system === "windows"
      ? "${workspaceFolder}\\\\.venv\\\\Scripts\\\\leka-architect.exe"
      : "${workspaceFolder}/.venv/bin/leka-architect";
  const env = system === "windows" ? "${workspaceFolder}\\\\.env" : "${workspaceFolder}/.env";
  return `{
  "servers": {
    "leka-architect": {
      "type": "stdio",
      "command": "${command}",
      "args": ["mcp"],
      "envFile": "${env}"
    }
  }
}`;
}

/** Its instructions in Copilot: the prompt file the package carries. */
function copilot(system: System): string {
  const copy =
    system === "windows"
      ? "Copy-Item -Recurse leka-architect\\copilot\\.github .github"
      : "cp -R leka-architect/copilot/.github .github";
  return `${copy}
# puis, dans le chat Copilot en mode Agent :
/architecte-applicatif Construis l'architecture du parcours Paiement CB sur le périmètre Digital`;
}

const CLAUDE = "claude mcp add leka-architect --env ARCHITECT_ENV=/chemin/absolu/vers/.env -- /chemin/absolu/vers/.venv/bin/leka-architect mcp";

const OTHER = `leka-architect prompts --output ./prompts
leka-architect pages --space MO --output pages.md
# … le modèle répond par le contenu du deck en JSON, enregistré dans deck.json :
leka-architect render-deck --deck deck.json --output ./rapport`;

const AZURE = `ARCHITECT_LLM_PROVIDER=azure
ARCHITECT_LLM_MODEL=<nom du déploiement>
ARCHITECT_LLM_BASE_URL=https://<ressource>.openai.azure.com
ARCHITECT_LLM_API_VERSION=2024-10-21
ARCHITECT_LLM_API_KEY=<clé>`;

function Copyable({ text, label }: { text: string; label: string }) {
  const t = useDictionary();
  const w = t.catalogue.install;
  const [copied, setCopied] = useState(false);
  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-medium text-brand-navy">{label}</span>
        <Button
          type="button"
          size="xs"
          variant="outline"
          onClick={async () => {
            try {
              await navigator.clipboard.writeText(text);
              setCopied(true);
              window.setTimeout(() => setCopied(false), 2000);
            } catch {
              setCopied(false);
            }
          }}
          data-testid="install-copy"
        >
          {copied ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />}
          {copied ? w.copied : w.copy}
        </Button>
      </div>
      <pre className="overflow-x-auto rounded-lg bg-brand-navy px-3 py-2 text-[0.75rem] leading-relaxed text-white">
        <code>{text}</code>
      </pre>
    </div>
  );
}

export function InstallAgent({ agentKey, className }: { agentKey: string; className?: string }) {
  const t = useDictionary();
  const w = t.catalogue.install;
  const [open, setOpen] = useState(false);
  const [system, setSystem] = useState<System>(() =>
    systemOf(typeof navigator === "undefined" ? "" : navigator.userAgent),
  );
  if (!INSTALLABLE.has(agentKey)) return null;
  const download = (
    <a
      href={apiAddress(`/capabilities/${encodeURIComponent(agentKey)}/package`)}
      className={buttonVariants({ size: "sm" })}
      download
      data-testid="install-download"
    >
      <Download aria-hidden="true" />
      {w.download}
    </a>
  );
  return (
    <>
      <Button
        type="button"
        size="sm"
        variant="outline"
        className={className}
        onClick={() => setOpen(true)}
        data-testid="install-open"
      >
        <PackageOpen aria-hidden="true" />
        {w.open}
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-2xl" data-testid="install-dialog">
          <DialogHeader>
            <DialogTitle>{w.title}</DialogTitle>
            <DialogDescription>{w.lead}</DialogDescription>
          </DialogHeader>
          {/* Its system: the commands below are its own. */}
          <div className="flex flex-wrap items-center gap-2" role="radiogroup" aria-label={w.system}>
            <span className="text-xs font-medium text-shell-muted">{w.system}</span>
            {SYSTEMS.map((name) => (
              <button
                key={name}
                type="button"
                role="radio"
                aria-checked={system === name}
                onClick={() => setSystem(name)}
                className={
                  system === name
                    ? "rounded-full bg-brand-navy px-3 py-1 text-xs font-medium text-white"
                    : "rounded-full bg-shell-canvas px-3 py-1 text-xs font-medium text-brand-navy hover:bg-brand-violet-soft/60"
                }
                data-testid={`install-system-${name}`}
              >
                {w.systems[name]}
              </button>
            ))}
          </div>
          <Tabs defaultValue="terminal">
            <TabsList>
              <TabsTab value="terminal" data-testid="install-tab-terminal">
                {w.terminal}
              </TabsTab>
              <TabsTab value="mcp" data-testid="install-tab-mcp">
                {w.mcp}
              </TabsTab>
              <TabsTab value="other" data-testid="install-tab-other">
                {w.other}
              </TabsTab>
            </TabsList>
            <TabsPanel value="terminal" className="flex flex-col gap-3 pt-4">
              <p className="text-[0.8125rem] text-shell-muted">{w.terminalLead}</p>
              {download}
              <Copyable label={w.install} text={INSTALL[system]} />
              <Copyable label={w.run} text={run(system)} />
              <Copyable label={w.docker} text={DOCKER} />
            </TabsPanel>
            <TabsPanel value="mcp" className="flex flex-col gap-3 pt-4">
              <p className="text-[0.8125rem] text-shell-muted">{w.mcpLead}</p>
              {download}
              <Copyable label={w.vscode} text={vscode(system)} />
              <Copyable label={w.copilot} text={copilot(system)} />
              <Copyable label={w.claude} text={CLAUDE} />
              <p className="text-xs text-shell-muted">{w.mcpMore}</p>
            </TabsPanel>
            <TabsPanel value="other" className="flex flex-col gap-3 pt-4">
              <p className="text-[0.8125rem] text-shell-muted">{w.otherLead}</p>
              {download}
              <Copyable label={w.azure} text={AZURE} />
              <Copyable label={w.pack} text={OTHER} />
            </TabsPanel>
          </Tabs>
          <p className="text-xs text-shell-muted">{w.private}</p>
        </DialogContent>
      </Dialog>
    </>
  );
}
