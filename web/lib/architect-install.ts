/**
 * The architect's installer (2026-10-25: « personne va le faire »): made in
 * the browser from what one types there — never sent to LEKA —, one command
 * to paste, then « Lancer l'architecte » to double-click. Pure: text in, text
 * out.
 *
 *   envText()       the .env it writes: Confluence, the model
 *   installer()     the script: Python checked, the downloaded agent unzipped
 *                   in ~/architecte, installed, its .env written, Copilot's
 *                   configuration put in place, its launcher made
 *   runCommand()    the one line to paste into the Terminal / PowerShell
 *
 * What is pasted into a terminal holds no comment: macOS' zsh runs « # … » as
 * a command. The scripts' own comments are read by bash and PowerShell, which
 * know them.
 */

export type System = "windows" | "macos" | "linux";

export type ModelKind =
  | "copilot"
  | "azure"
  | "anthropic"
  | "gemini"
  | "mistral"
  | "openai"
  | "other";

export type Setup = {
  confluenceUrl: string;
  confluenceEmail: string;
  confluenceToken: string;
  model: ModelKind;
  modelName: string;
  modelKey: string;
  modelUrl: string;
};

/** Each model as the agent reaches it: its API's format, its defaults, where
 * its key is made. */
export const MODELS: Record<
  ModelKind,
  { provider: "" | "openai" | "azure" | "anthropic"; name: string; url: string; keyPage: string }
> = {
  copilot: { provider: "", name: "", url: "", keyPage: "" },
  azure: { provider: "azure", name: "", url: "", keyPage: "https://portal.azure.com" },
  anthropic: {
    provider: "anthropic",
    name: "claude-sonnet-5",
    url: "",
    keyPage: "https://console.anthropic.com/settings/keys",
  },
  gemini: {
    provider: "openai",
    name: "gemini-3.8-flash",
    url: "https://generativelanguage.googleapis.com/v1beta/openai",
    keyPage: "https://aistudio.google.com/apikey",
  },
  mistral: {
    provider: "openai",
    name: "mistral-large-latest",
    url: "https://api.mistral.ai/v1",
    keyPage: "https://console.mistral.ai/api-keys",
  },
  openai: {
    provider: "openai",
    name: "gpt-4.1",
    url: "",
    keyPage: "https://platform.openai.com/api-keys",
  },
  other: { provider: "openai", name: "", url: "", keyPage: "" },
};

export const TOKEN_PAGE = "https://id.atlassian.com/manage-profile/security/api-tokens";

export const EMPTY_SETUP: Setup = {
  confluenceUrl: "",
  confluenceEmail: "",
  confluenceToken: "",
  model: "copilot",
  modelName: "",
  modelKey: "",
  modelUrl: "",
};

/** One line, as .env reads it: no line break can add another line — nor end
 * the script's here-document early. */
export function oneLine(value: string): string {
  return value.replace(/[\r\n]+/g, " ").trim();
}

/** Whether anything was typed: else the installer leaves .env to be filled. */
export function given(setup: Setup): boolean {
  return Boolean(
    oneLine(setup.confluenceUrl) ||
      oneLine(setup.confluenceToken) ||
      (setup.model !== "copilot" && oneLine(setup.modelKey)),
  );
}

export function envText(setup: Setup): string {
  const model = MODELS[setup.model];
  const lines = [
    "# L'Architecte applicatif : sa configuration, écrite par son installateur.",
    "# Votre Confluence, lu et jamais modifié.",
    `CONFLUENCE_URL=${oneLine(setup.confluenceUrl)}`,
    `CONFLUENCE_EMAIL=${oneLine(setup.confluenceEmail)}`,
    `CONFLUENCE_TOKEN=${oneLine(setup.confluenceToken)}`,
    "",
  ];
  if (setup.model === "copilot") {
    lines.push("# Le modèle : celui de Copilot ou de Claude, dans VS Code. Rien à mettre ici.");
  } else {
    lines.push(
      "# Le modèle.",
      `ARCHITECT_LLM_PROVIDER=${model.provider}`,
      `ARCHITECT_LLM_MODEL=${oneLine(setup.modelName)}`,
      `ARCHITECT_LLM_API_KEY=${oneLine(setup.modelKey)}`,
      `ARCHITECT_LLM_BASE_URL=${oneLine(setup.modelUrl)}`,
    );
    if (setup.model === "azure") lines.push("ARCHITECT_LLM_API_VERSION=2024-10-21");
  }
  lines.push(
    "",
    "# Les fichiers de Connaissances (l'annuaire des contacts, en Excel...) : ce dossier.",
    "ARCHITECT_KNOWLEDGE_DIR=./connaissances",
    "",
  );
  return lines.join("\n");
}

export function installerName(system: System): string {
  return system === "windows" ? "installer-architecte.ps1" : "installer-architecte.sh";
}

/** The one line to paste — the newest installer of Downloads, run. */
export function runCommand(system: System): string {
  return system === "windows"
    ? "powershell -ExecutionPolicy Bypass -File (Get-ChildItem $HOME\\Downloads\\installer-architecte*.ps1 | Sort-Object LastWriteTime | Select-Object -Last 1).FullName"
    : 'bash "$(ls -t ~/Downloads/installer-architecte*.sh | head -1)"';
}

/** The launcher's file, in ~/architecte. */
export function launcherName(system: System): string {
  if (system === "windows") return "Lancer l'architecte.bat";
  return system === "macos" ? "Lancer l'architecte.command" : "lancer-architecte.sh";
}

const PYTHON_HINT: Record<System, string> = {
  windows:
    "https://www.python.org/downloads/windows/ (à l'installation, cochez « Add python.exe to PATH »)",
  macos: "https://www.python.org/downloads/macos/ (ou : brew install python@3.12)",
  linux: "sudo apt install python3 python3-venv",
};

/** Its launcher on macOS and Linux: Copilot's way when no model is in .env,
 * else the spaces, the questions, the deck, its folder opened. */
function bashLauncher(system: "macos" | "linux"): string {
  const open = system === "macos" ? "open" : "xdg-open";
  const vscode =
    system === "macos" ? 'open -a "Visual Studio Code" . >/dev/null 2>&1' : "code . >/dev/null 2>&1";
  return `#!/usr/bin/env bash
# L'Architecte applicatif de LEKA : le lancer.
cd "$(dirname "$0")"
pause() { echo; printf "Appuyez sur Entrée pour fermer. "; read -r _ || true; }
echo
echo "L'Architecte applicatif de LEKA"
echo
if ! grep -Eq '^ARCHITECT_LLM_MODEL=.+' .env 2>/dev/null; then
  echo "Il réfléchit avec Copilot ou Claude, dans VS Code. Ouvrez-y ce dossier,"
  echo "puis, dans le chat Copilot en mode Agent, tapez :"
  echo
  echo "  /architecte-applicatif Construis l'architecture du parcours ... sur le périmètre ..."
  echo
  ${vscode} || echo "(Dans VS Code : Fichier > Ouvrir le dossier... > architecte)"
  echo "Pour qu'il réfléchisse seul, sans VS Code : mettez un modèle dans le fichier .env de ce dossier."
  pause
  exit 0
fi
printf "Un mot du nom de votre espace Confluence (Entrée : tous) : "
read -r MOT || true
echo
if [ -n "$MOT" ]; then
  .venv/bin/leka-architect spaces | grep -i -- "$MOT" || echo "Aucun espace ne contient : $MOT"
else
  .venv/bin/leka-architect spaces
fi
echo
printf "La clé de l'espace (à gauche ci-dessus) : "; read -r ESPACE || true
printf "Le parcours (ex. Paiement CB) : "; read -r PARCOURS || true
printf "Le périmètre (ex. Digital - Espace Client) : "; read -r PERIMETRE || true
SORTIE="rapport/$(date +%Y-%m-%d-%Hh%M)"
echo
echo "C'est parti : 3 à 5 minutes."
if .venv/bin/leka-architect deck --space "$ESPACE" --parcours "$PARCOURS" --perimetre "$PERIMETRE" --output "$SORTIE"; then
  echo
  echo "Terminé : le PowerPoint et le PDF sont dans $SORTIE"
  ${open} "$SORTIE" >/dev/null 2>&1 || true
fi
pause
`;
}

function bashInstaller(system: "macos" | "linux", setup: Setup): string {
  const launcher = launcherName(system);
  const open = system === "macos" ? "open" : "xdg-open";
  const env = given(setup)
    ? `cat > .env <<'LEKA_ENV_FIN'
${envText(setup)}LEKA_ENV_FIN
chmod 600 .env
echo "4/5  Vos informations : dans $DOSSIER/.env"`
    : `[ -f .env ] || cp leka-architect/.env.example .env
echo "4/5  Vos informations : à écrire dans $DOSSIER/.env (il va s'ouvrir)"`;
  const fill = given(setup)
    ? ""
    : system === "macos"
      ? "open -e .env >/dev/null 2>&1 || true\n"
      : 'echo "Écrivez vos informations dans $DOSSIER/.env (Confluence, et votre modèle)."\n';
  return `#!/usr/bin/env bash
# L'Architecte applicatif de LEKA : son installation (${system === "macos" ? "macOS" : "Linux"}).
# Fabriqué par votre navigateur. Il porte vos identifiants : il s'efface à la fin.
set -eu
SOI="$0"
DOSSIER="$HOME/architecte"
LANCEUR="${launcher}"
fin() { echo; echo "$1"; echo; exit 1; }
echo
echo "L'Architecte applicatif : installation dans $DOSSIER"
echo
PY=""
for candidat in python3.14 python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$candidat" >/dev/null 2>&1 && "$candidat" -c 'import sys; sys.exit(sys.version_info < (3, 10))' >/dev/null 2>&1; then
    PY="$candidat"
    break
  fi
done
[ -n "$PY" ] || fin "Il faut Python 3.10 ou plus : ${PYTHON_HINT[system]}. Puis relancez la même commande."
echo "1/5  Python : $("$PY" --version 2>&1)"
SOURCE="$(ls -t "$HOME"/Downloads/leka-architect*.zip 2>/dev/null | head -1 || true)"
mkdir -p "$DOSSIER"
cd "$DOSSIER"
if [ -n "$SOURCE" ]; then
  rm -rf leka-architect
  "$PY" -m zipfile -e "$SOURCE" .
elif [ -f "$HOME/Downloads/leka-architect/pyproject.toml" ]; then
  rm -rf leka-architect
  cp -R "$HOME/Downloads/leka-architect" leka-architect
  rm -rf leka-architect/.venv
else
  fin "L'agent n'est pas dans Téléchargements : dans LEKA, cliquez d'abord sur « Télécharger l'agent », puis relancez la même commande."
fi
echo "2/5  L'agent : dans $DOSSIER/leka-architect"
[ -d .venv ] || "$PY" -m venv .venv
.venv/bin/python -m pip install --quiet --disable-pip-version-check --upgrade ./leka-architect || fin "L'installation a échoué : il faut Internet (PyPI). Derrière un proxy d'entreprise, voyez avec votre informatique, puis relancez la même commande."
echo "3/5  Installé : $(.venv/bin/leka-architect --version)"
${env}
mkdir -p .vscode connaissances rapport
cp leka-architect/mcp/vscode-copilot.json .vscode/mcp.json
if [ -d leka-architect/copilot/.github ]; then
  rm -rf .github
  cp -R leka-architect/copilot/.github .github
fi
cat > "$LANCEUR" <<'LEKA_LANCEUR_FIN'
${bashLauncher(system)}LEKA_LANCEUR_FIN
chmod +x "$LANCEUR"
echo "5/5  Le bouton « Lancer l'architecte » : $DOSSIER/$LANCEUR"
if grep -Eq '^CONFLUENCE_TOKEN=.+' .env; then
  echo
  echo "Vérification, vos espaces Confluence :"
  .venv/bin/leka-architect spaces 2>&1 | head -15 || true
fi
echo
echo "C'est installé. Pour lancer l'architecte : double-cliquez sur « Lancer l'architecte » dans le dossier architecte."
${open} "$DOSSIER" >/dev/null 2>&1 || true
${fill}rm -f -- "$SOI"
`;
}

/** Its launcher on Windows: PowerShell, so its words keep their accents. */
const POWERSHELL_LAUNCHER = `Set-Location $PSScriptRoot
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$Agent = Join-Path $PSScriptRoot ".venv\\Scripts\\leka-architect.exe"
function Pause-Fin { Write-Host ""; Read-Host "Appuyez sur Entrée pour fermer" | Out-Null }
Write-Host ""
Write-Host "L'Architecte applicatif de LEKA"
Write-Host ""
if (-not (Select-String -Path ".env" -Pattern "^ARCHITECT_LLM_MODEL=.+" -Quiet)) {
  Write-Host "Il réfléchit avec Copilot ou Claude, dans VS Code. Ouvrez-y ce dossier,"
  Write-Host "puis, dans le chat Copilot en mode Agent, tapez :"
  Write-Host ""
  Write-Host "  /architecte-applicatif Construis l'architecture du parcours ... sur le périmètre ..."
  Write-Host ""
  try { & code $PSScriptRoot } catch { Write-Host "(Dans VS Code : Fichier > Ouvrir le dossier... > architecte)" }
  Write-Host "Pour qu'il réfléchisse seul, sans VS Code : mettez un modèle dans le fichier .env de ce dossier."
  Pause-Fin
  exit 0
}
$Mot = Read-Host "Un mot du nom de votre espace Confluence (Entrée : tous)"
Write-Host ""
if ($Mot) {
  $Trouves = & $Agent spaces | Select-String -SimpleMatch $Mot
  if ($Trouves) { $Trouves | ForEach-Object { Write-Host $_.Line } } else { Write-Host "Aucun espace ne contient : $Mot" }
} else {
  & $Agent spaces
}
Write-Host ""
$Espace = Read-Host "La clé de l'espace (à gauche ci-dessus)"
$Parcours = Read-Host "Le parcours (ex. Paiement CB)"
$Perimetre = Read-Host "Le périmètre (ex. Digital - Espace Client)"
$Sortie = Join-Path "rapport" (Get-Date -Format "yyyy-MM-dd-HH'h'mm")
Write-Host ""
Write-Host "C'est parti : 3 à 5 minutes."
& $Agent deck --space $Espace --parcours $Parcours --perimetre $Perimetre --output $Sortie
if ($LASTEXITCODE -eq 0) {
  Write-Host ""
  Write-Host "Terminé : le PowerPoint et le PDF sont dans $Sortie"
  Invoke-Item $Sortie
}
Pause-Fin
`;

function powershellInstaller(setup: Setup): string {
  const env = given(setup)
    ? `$Configuration = @'
${envText(setup)}'@
Set-Content -Path (Join-Path $Dossier ".env") -Value $Configuration -Encoding UTF8
Write-Host "4/5  Vos informations : dans $Dossier\\.env"`
    : `if (-not (Test-Path ".env")) { Copy-Item "leka-architect\\.env.example" ".env" }
Write-Host "4/5  Vos informations : à écrire dans $Dossier\\.env (il va s'ouvrir)"`;
  const fill = given(setup) ? "" : 'notepad (Join-Path $Dossier ".env")\n';
  return `# L'Architecte applicatif de LEKA : son installation (Windows).
# Fabriqué par votre navigateur. Il porte vos identifiants : il s'efface à la fin.
$ErrorActionPreference = "Stop"
$Soi = $PSCommandPath
$Dossier = Join-Path $HOME "architecte"
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
function Fin([string]$Dit) {
  Write-Host ""
  Write-Host $Dit -ForegroundColor Yellow
  Write-Host ""
  exit 1
}
function Test-Python([string]$Exe, [string[]]$Avant) {
  try {
    & $Exe @Avant -c "import sys; sys.exit(sys.version_info < (3, 10))" | Out-Null
    return ($LASTEXITCODE -eq 0)
  } catch {
    return $false
  }
}
Write-Host ""
Write-Host "L'Architecte applicatif : installation dans $Dossier"
Write-Host ""
$Py = $null
$Avant = @()
if (Test-Python "py" @("-3")) { $Py = "py"; $Avant = @("-3") }
elseif (Test-Python "python" @()) { $Py = "python" }
if (-not $Py) { Fin "Il faut Python 3.10 ou plus : ${PYTHON_HINT.windows}. Puis relancez la même commande." }
Write-Host ("1/5  Python : " + (& $Py @Avant --version))
$Telechargements = Join-Path $HOME "Downloads"
try {
  $Connu = (New-Object -ComObject Shell.Application).NameSpace("shell:Downloads").Self.Path
  if ($Connu) { $Telechargements = $Connu }
} catch { }
$Zip = Get-ChildItem -Path $Telechargements -Filter "leka-architect*.zip" -ErrorAction SilentlyContinue | Sort-Object LastWriteTime | Select-Object -Last 1
New-Item -ItemType Directory -Force -Path $Dossier | Out-Null
Set-Location $Dossier
$Paquet = Join-Path $Dossier "leka-architect"
if (Test-Path $Paquet) { Remove-Item -Recurse -Force $Paquet }
if ($Zip) {
  Expand-Archive -Path $Zip.FullName -DestinationPath $Dossier -Force
} elseif (Test-Path (Join-Path $Telechargements "leka-architect\\pyproject.toml")) {
  Copy-Item -Recurse -Force (Join-Path $Telechargements "leka-architect") $Paquet
  if (Test-Path (Join-Path $Paquet ".venv")) { Remove-Item -Recurse -Force (Join-Path $Paquet ".venv") }
} else {
  Fin "L'agent n'est pas dans Téléchargements : dans LEKA, cliquez d'abord sur « Télécharger l'agent », puis relancez la même commande."
}
Write-Host "2/5  L'agent : dans $Paquet"
if (-not (Test-Path ".venv")) {
  & $Py @Avant -m venv .venv
  if ($LASTEXITCODE -ne 0) { Fin "Python n'a pas pu créer l'environnement .venv : relancez la même commande." }
}
& .\\.venv\\Scripts\\python.exe -m pip install --quiet --disable-pip-version-check --upgrade .\\leka-architect
if ($LASTEXITCODE -ne 0) { Fin "L'installation a échoué : il faut Internet (PyPI). Derrière un proxy d'entreprise, voyez avec votre informatique, puis relancez la même commande." }
Write-Host ("3/5  Installé : " + (& .\\.venv\\Scripts\\leka-architect.exe --version))
${env}
New-Item -ItemType Directory -Force -Path ".vscode", "connaissances", "rapport" | Out-Null
Copy-Item -Force "leka-architect\\mcp\\vscode-copilot-windows.json" ".vscode\\mcp.json"
if (Test-Path "leka-architect\\copilot\\.github") {
  if (Test-Path ".github") { Remove-Item -Recurse -Force ".github" }
  Copy-Item -Recurse -Force "leka-architect\\copilot\\.github" ".github"
}
$Lanceur = @'
${POWERSHELL_LAUNCHER}'@
Set-Content -Path (Join-Path $Dossier "lancer.ps1") -Value $Lanceur -Encoding UTF8
Set-Content -Path (Join-Path $Dossier "${launcherName("windows")}") -Value @("@echo off", 'powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0lancer.ps1"') -Encoding ASCII
Write-Host "5/5  Le bouton « Lancer l'architecte » : dans $Dossier"
if (Select-String -Path ".env" -Pattern "^CONFLUENCE_TOKEN=.+" -Quiet) {
  Write-Host ""
  Write-Host "Vérification, vos espaces Confluence :"
  & .\\.venv\\Scripts\\leka-architect.exe spaces | Select-Object -First 15
}
Write-Host ""
Write-Host "C'est installé. Pour lancer l'architecte : double-cliquez sur « Lancer l'architecte » dans le dossier architecte."
Invoke-Item $Dossier
${fill}Remove-Item -Force $Soi
`;
}

/** The installer of `system`, with `setup` in it — a BOM before Windows' so
 * Windows PowerShell 5.1 reads its accents. */
export function installer(system: System, setup: Setup): string {
  if (system === "windows") return `﻿${powershellInstaller(setup)}`;
  return bashInstaller(system, setup);
}

// ── By hand: the same steps, pasted block by block — for a computer that
//    refuses scripts. No comment in a block: macOS' zsh runs « # … ». ─────

const FOLDER: Record<System, string> = { windows: "$HOME\\architecte", macos: "~/architecte", linux: "~/architecte" };
const BIN: Record<System, string> = {
  windows: ".venv\\Scripts\\leka-architect",
  macos: ".venv/bin/leka-architect",
  linux: ".venv/bin/leka-architect",
};
const OPEN: Record<System, string> = { windows: "explorer rapport", macos: "open rapport", linux: "xdg-open rapport" };

const MANUAL_INSTALL: Record<System, string> = {
  windows: `New-Item -ItemType Directory -Force $HOME\\architecte | Out-Null; cd $HOME\\architecte
$zip = (Get-ChildItem $HOME\\Downloads\\leka-architect*.zip | Sort-Object LastWriteTime | Select-Object -Last 1).FullName
Expand-Archive $zip -DestinationPath . -Force
py -3 -m venv .venv
.venv\\Scripts\\python -m pip install .\\leka-architect
Copy-Item leka-architect\\.env.example .env
notepad .env`,
  macos: `mkdir -p ~/architecte && cd ~/architecte
unzip -o "$(ls -t ~/Downloads/leka-architect*.zip | head -1)"
python3 -m venv .venv
.venv/bin/pip install ./leka-architect
cp leka-architect/.env.example .env && open -e .env`,
  linux: `mkdir -p ~/architecte && cd ~/architecte
unzip -o "$(ls -t ~/Downloads/leka-architect*.zip | head -1)"
python3 -m venv .venv
.venv/bin/pip install ./leka-architect
cp leka-architect/.env.example .env && nano .env`,
};

const MANUAL_ENV = `CONFLUENCE_URL=https://votre-entreprise.atlassian.net
CONFLUENCE_EMAIL=prenom.nom@entreprise.com
CONFLUENCE_TOKEN=votre token
ARCHITECT_LLM_PROVIDER=azure
ARCHITECT_LLM_MODEL=le nom du déploiement
ARCHITECT_LLM_API_KEY=votre clé
ARCHITECT_LLM_BASE_URL=https://votre-ressource.openai.azure.com`;

export const MANUAL: Record<System, { install: string; env: string; check: string; run: string }> = Object.fromEntries(
  (["windows", "macos", "linux"] as const).map((system) => [
    system,
    {
      install: MANUAL_INSTALL[system],
      env: MANUAL_ENV,
      check: `cd ${FOLDER[system]}\n${BIN[system]} spaces`,
      run: `${BIN[system]} deck --space MO --parcours "Paiement CB" --perimetre "Digital - Espace Client" --output rapport\n${OPEN[system]}`,
    },
  ]),
) as Record<System, { install: string; env: string; check: string; run: string }>;
