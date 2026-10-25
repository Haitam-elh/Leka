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
 * copy.
 */

/** The agents a customer may install: their package is built from LEKA's own code. */
export const INSTALLABLE: ReadonlySet<string> = new Set(["application-architecture"]);

const TERMINAL = `unzip leka-architect-*.zip
pip install ./leka-architect
cp leka-architect/.env.example .env      # puis remplissez-le : Confluence et votre modèle
leka-architect tree --space ARCHI
leka-architect simulate --space ARCHI --output ./rapport`;

const DOCKER = `docker build -t leka-architect ./leka-architect
docker run --rm --env-file .env -v "$PWD/rapport:/travail/rapport" leka-architect simulate --space ARCHI --output rapport`;

const VSCODE = `{
  "servers": {
    "leka-architect": {
      "type": "stdio",
      "command": "leka-architect",
      "args": ["mcp"],
      "envFile": "\${workspaceFolder}/.env"
    }
  }
}`;

const CLAUDE = "claude mcp add leka-architect --env ARCHITECT_ENV=/chemin/absolu/vers/.env -- leka-architect mcp";

const OTHER = `leka-architect prompts --output ./prompts
leka-architect pages --space ARCHI --output pages.md
# … le modèle répond en JSON, enregistré dans reponse.json :
leka-architect render --dossier reponse.json --space ARCHI --output ./rapport`;

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
              <Copyable label={w.install} text={TERMINAL} />
              <Copyable label={w.docker} text={DOCKER} />
            </TabsPanel>
            <TabsPanel value="mcp" className="flex flex-col gap-3 pt-4">
              <p className="text-[0.8125rem] text-shell-muted">{w.mcpLead}</p>
              {download}
              <Copyable label={w.vscode} text={VSCODE} />
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
