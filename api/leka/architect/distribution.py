"""What ships with the downloadable architect, besides its code: its README,
its .env.example, its Dockerfile, its MCP configurations — one per client,
VS Code's for Windows and for macOS / Linux —, Copilot's prompt and its
prompt pack for models without tools. Written here, from the same prompts
and sections as the code, so the pack never says other than the agent does.

Python 3.10 or later (2026-10-25): the deck it draws is LEKA's renderer,
which needs pydantic, python-pptx and reportlab.
"""

from __future__ import annotations

import json

from . import __version__
from .journey import TOOLS_NOTE
from .model import ELEMENT_TYPES, RELATION_TYPES, SCHEMA, SECTIONS
from .prompts import SYSTEM

PYPROJECT = f"""[build-system]
requires = ["setuptools>=61"]
build-backend = "setuptools.build_meta"

[project]
name = "leka-architect"
version = "{__version__}"
description = "L'Architecte applicatif de LEKA : Confluence vers le deck d'architecture d'un parcours (PowerPoint, PDF) et le dossier ArchiMate, sur votre LLM."
readme = "README.md"
requires-python = ">=3.10"
dependencies = ["reportlab>=3.6", "python-pptx>=1.0", "pydantic>=2.6"]

[project.scripts]
leka-architect = "leka_architect.cli:main"

[tool.setuptools]
packages = ["leka_architect", "leka_architect.deck"]

[tool.setuptools.package-data]
leka_architect = ["*.md"]
"""

ENV_EXAMPLE = """# L'Architecte applicatif — sa configuration. Copiez ce fichier en .env
# et remplissez-le. Il ne quitte jamais votre poste.

# ── Confluence, par son API ──────────────────────────────────────────────
# Cloud : https://votre-site.atlassian.net, l'adresse e-mail du compte et un
# token API (id.atlassian.com → Sécurité → Tokens d'API).
# Data Center : l'adresse du serveur, sans e-mail, un token d'accès personnel.
CONFLUENCE_URL=https://votre-site.atlassian.net
CONFLUENCE_EMAIL=prenom.nom@entreprise.com
CONFLUENCE_TOKEN=

# … ou un export sur disque (un export HTML ou Markdown, ou celui de l'outil
# de copie) : l'API n'est alors pas appelée.
# ARCHITECT_CONFLUENCE_EXPORT=/chemin/vers/export

# ── Le modèle ────────────────────────────────────────────────────────────
# anthropic : Claude.  openai : toute API compatible OpenAI (OpenAI, Mistral,
# Ollama, vLLM, LM Studio, un LLM interne).  azure : Azure OpenAI.
ARCHITECT_LLM_PROVIDER=azure
# Azure : le nom de votre déploiement. Sinon : le modèle (claude-sonnet-5,
# gpt-4.1, mistral-large-latest, llama3.1…).
ARCHITECT_LLM_MODEL=
ARCHITECT_LLM_API_KEY=
# Azure : https://<ressource>.openai.azure.com — Ollama : http://localhost:11434/v1
# — vide : l'adresse publique du fournisseur.
ARCHITECT_LLM_BASE_URL=
# Azure seulement.
ARCHITECT_LLM_API_VERSION=2024-10-21

# ── Les fichiers de Connaissances ────────────────────────────────────────
# L'annuaire des contacts (Excel), le référentiel applicatif… : le dossier où
# ils sont. Ils servent au RACI ; rien d'autre n'est lu sur votre poste.
ARCHITECT_KNOWLEDGE_DIR=./connaissances
"""

DOCKERFILE = """FROM python:3.12-slim
WORKDIR /opt/leka-architect
COPY . .
RUN pip install --no-cache-dir . && useradd --create-home architecte
USER architecte
WORKDIR /travail
ENTRYPOINT ["leka-architect"]
CMD ["--help"]
"""

MCP: dict[str, object] = {
    # Copilot in VS Code: the .venv of the working folder, its .env.
    "vscode-copilot.json": {
        "servers": {
            "leka-architect": {
                "type": "stdio",
                "command": "${workspaceFolder}/.venv/bin/leka-architect",
                "args": ["mcp"],
                "envFile": "${workspaceFolder}/.env",
            }
        }
    },
    "vscode-copilot-windows.json": {
        "servers": {
            "leka-architect": {
                "type": "stdio",
                "command": "${workspaceFolder}\\.venv\\Scripts\\leka-architect.exe",
                "args": ["mcp"],
                "envFile": "${workspaceFolder}\\.env",
            }
        }
    },
    "claude-desktop.json": {
        "mcpServers": {
            "leka-architect": {
                "command": "leka-architect",
                "args": ["mcp"],
                "env": {"ARCHITECT_ENV": "/chemin/absolu/vers/.env"},
            }
        }
    },
    "cursor.json": {
        "mcpServers": {
            "leka-architect": {
                "command": "leka-architect",
                "args": ["mcp"],
                "env": {"ARCHITECT_ENV": "/chemin/absolu/vers/.env"},
            }
        }
    },
    "docker.json": {
        "servers": {
            "leka-architect": {
                "type": "stdio",
                "command": "docker",
                "args": [
                    "run",
                    "-i",
                    "--rm",
                    "--env-file",
                    "/chemin/absolu/vers/.env",
                    "leka-architect",
                    "mcp",
                ],
            }
        }
    },
}

CLAUDE_CODE = "claude mcp add leka-architect --env ARCHITECT_ENV=/chemin/absolu/vers/.env -- leka-architect mcp"


def copilot_prompt(instructions: str) -> str:
    """Copilot's prompt file in VS Code (.github/prompts/…prompt.md): the
    instructions, in agent mode, its tools — this package's MCP server's."""
    return (
        "---\n"
        "mode: agent\n"
        "description: Architecte applicatif — le deck d'architecture d'un parcours "
        "(PowerPoint et PDF), depuis Confluence\n"
        "---\n\n"
        f"{instructions.strip()}\n\n{TOOLS_NOTE}\n"
    )


def prompt_pack(instructions: str | None = None) -> dict[str, str]:
    """For a chat model without tools — ChatGPT, Copilot chat: the
    instructions it follows (`instructions`, the deck's), the dossier's, its
    template, and how to give it the pages."""
    sections = "\n".join(f"{n}. {title} (`{key}`)" for n, (key, title) in enumerate(SECTIONS, 1))
    types = "\n".join(
        f"- **{layer}** : {', '.join(kinds)}" for layer, kinds in ELEMENT_TYPES.items()
    )
    pack = {
        "instructions-systeme.md": SYSTEM + "\n",
        "modele-livrable.md": f"""# Le dossier d'architecture — son modèle

Le modèle répond par un objet JSON, que `leka-architect render` écrit en
Markdown, PDF et Word, chaque section citant ses pages.

## Ses sections

{sections}

## Les types d'éléments ArchiMate, par couche

{types}

## Les relations

{", ".join(RELATION_TYPES)}

## Le schéma de la réponse

```json
{json.dumps(SCHEMA, ensure_ascii=False, indent=2)}
```
""",
        "mode-emploi.md": """# Utiliser l'Architecte avec un LLM sans outils (ChatGPT, Copilot chat…)

## Le deck d'un parcours (PowerPoint et PDF)

1. **Les consignes.** Collez `consignes-architecte.md` en instructions
   personnalisées (ou en premier message).

2. **Les pages.** Depuis Confluence (Paramètres de l'espace → Exporter
   l'espace, en HTML), ou par l'API :

       leka-architect pages --space MO --output pages.md

   Joignez `pages.md` et, pour le RACI, l'annuaire des contacts.

3. **La demande.** « Construis l'architecture du parcours [parcours] sur le
   périmètre [périmètre]. Réponds par le contenu du deck en JSON, selon le
   schéma joint » — le schéma : `leka-architect prompts` l'écrit
   (`schema-deck.json`).

4. **Le livrable.** Enregistrez la réponse dans `deck.json`, puis :

       leka-architect render-deck --deck deck.json --output rapport

   Le PowerPoint modifiable et le PDF sont écrits dans `rapport/`, au gabarit.

## Le dossier ArchiMate d'un espace (Markdown, PDF, Word)

1. **Les pages** : `leka-architect pages --space ARCHI --output pages.md`.
2. **Les consignes** : `instructions-systeme.md`.
3. **La demande** : « Produis le dossier d'architecture en JSON, selon le
   schéma » (`modele-livrable.md`), `pages.md` joint.
4. **Le livrable** : la réponse dans `reponse.json`, puis

       leka-architect render --dossier reponse.json --space ARCHI --output rapport
""",
    }
    if instructions:
        pack["consignes-architecte.md"] = instructions.strip() + "\n"
    return pack


README = f"""# L'Architecte applicatif — version installable (v{__version__})

Il lit votre Confluence et produit :

- **le deck d'architecture d'un parcours** — PowerPoint modifiable et PDF, au
  gabarit de vos consignes : page de titre et sommaire, le parcours en clair,
  les règles de gestion, une slide par sous-processus (couche métier ArchiMate
  et couche applicative en diagramme de séquence), le RACI, les points de
  contrôle, les sources ;
- **le dossier ArchiMate d'un espace** — Markdown, PDF, Word, chaque section
  citant ses pages.

Il suit **les consignes de votre organisation** (`leka_architect/consignes.md`,
`prompts/consignes-architecte.md`) quand LEKA les a reçues ; sinon celles de
LEKA. Les fichiers PowerPoint et PDF sont dessinés par **le même code que sur
LEKA**. **Rien ne passe par LEKA** : vos pages vont au modèle que vous
configurez, et nulle part ailleurs. Aucune télémétrie.

## 1. Installer (moins de 10 minutes)

Il faut **Python 3.10 ou plus**. Travaillez dans un dossier à vous — par
exemple `architecte/` —, où vous dézippez ce paquet : `architecte/leka-architect/`.
Les commandes ci-dessous se tapent dans ce dossier `architecte/`.

### Windows (PowerShell)

Python : https://www.python.org/downloads/windows/ — à l'installation, cochez
« Add python.exe to PATH ». Puis :

    py -3 --version
    py -3 -m venv .venv
    .venv\\Scripts\\python -m pip install .\\leka-architect
    Copy-Item leka-architect\\.env.example .env
    notepad .env
    .venv\\Scripts\\leka-architect --version

(`py` est le lanceur de python.org. Sans lui : `python` à la place de `py -3`.
Pas besoin d'« activer » l'environnement : on appelle `.venv\\Scripts\\…`.)

### macOS (Terminal)

`python3 --version` doit dire 3.10 ou plus — sinon : `brew install python@3.12`,
ou https://www.python.org/downloads/macos/. Puis :

    python3 -m venv .venv
    .venv/bin/pip install ./leka-architect
    cp leka-architect/.env.example .env
    open -e .env
    .venv/bin/leka-architect --version

### Linux

`python3 --version` doit dire 3.10 ou plus ; sous Debian / Ubuntu, s'il manque :
`sudo apt install python3 python3-venv`. Puis :

    python3 -m venv .venv
    .venv/bin/pip install ./leka-architect
    cp leka-architect/.env.example .env
    nano .env
    .venv/bin/leka-architect --version

### Avec Docker (tous systèmes)

    docker build -t leka-architect ./leka-architect
    docker run --rm --env-file .env -v "$PWD:/travail" leka-architect --version

Dans la suite, `leka-architect` veut dire `.venv\\Scripts\\leka-architect`
(Windows) ou `.venv/bin/leka-architect` (macOS, Linux).

## 2. Configurer

Remplissez `.env` (il ne quitte jamais votre poste) :

- **Confluence** : son adresse, l'adresse e-mail du compte et un token API
  (Cloud : https://id.atlassian.com/manage-profile/security/api-tokens), ou
  un token d'accès personnel (Data Center). Lecture seule : rien n'est jamais
  écrit dans Confluence. Un export sur disque marche aussi
  (`ARCHITECT_CONFLUENCE_EXPORT`).
- **Le modèle** :
  - Azure OpenAI : `ARCHITECT_LLM_PROVIDER=azure`, le nom du déploiement dans
    `ARCHITECT_LLM_MODEL`, `ARCHITECT_LLM_BASE_URL=https://<ressource>.openai.azure.com`,
    `ARCHITECT_LLM_API_VERSION`, la clé.
  - Claude : `ARCHITECT_LLM_PROVIDER=anthropic`, `ARCHITECT_LLM_MODEL=claude-sonnet-5`, la clé.
  - Toute API compatible OpenAI (OpenAI, Mistral, Ollama, vLLM, LM Studio, un
    LLM interne) : `ARCHITECT_LLM_PROVIDER=openai`, son adresse dans
    `ARCHITECT_LLM_BASE_URL`, son modèle.
  - Avec Copilot ou Claude en MCP (§ 4), le modèle est le leur : rien à mettre ici.
- **Les fichiers de Connaissances** (pour le RACI) : l'annuaire des contacts
  en Excel et le référentiel applicatif, dans le dossier de
  `ARCHITECT_KNOWLEDGE_DIR` (par défaut `./connaissances`).

Vérifiez ce qu'il lit :

    leka-architect spaces
    leka-architect tree --space MO

## 3. Le deck d'un parcours

    leka-architect deck --space MO --parcours "Paiement CB" --perimetre "Digital - Espace Client" --output rapport
    leka-architect deck --space MO --root-page 123456 --parcours "Paiement CB" --perimetre "Digital" --vue-applicative --output rapport

Dans `rapport/` : `architecture-paiement-cb.pptx` (modifiable),
`architecture-paiement-cb.pdf`, et son contenu en JSON.

Et le dossier ArchiMate d'un espace :

    leka-architect simulate --space ARCHI --output rapport

## 4. Dans GitHub Copilot (VS Code), Claude ou Cursor (MCP)

    leka-architect mcp

expose les outils `list_confluence_spaces`, `list_confluence_tree`,
`read_confluence_page`, `search_confluence_pages`, `list_knowledge_files`,
`read_knowledge_file`, `generate_architecture_deck`, `analyze_architecture`,
`generate_architecture_document`, et la consigne `architecte`.

**GitHub Copilot dans VS Code** (mode agent) — ouvrez le dossier `architecte/` dans VS Code :

1. Copiez `leka-architect/mcp/vscode-copilot-windows.json` (Windows) ou
   `leka-architect/mcp/vscode-copilot.json` (macOS, Linux) en `.vscode/mcp.json`.
2. Copiez le dossier `leka-architect/copilot/.github` à la racine : il donne à
   Copilot les consignes de l'architecte (`/architecte-applicatif`).
3. Dans le chat Copilot, mode **Agent** : `/architecte-applicatif Construis
   l'architecture du parcours Paiement CB sur le périmètre Digital`.

**Claude Desktop** : `mcp/claude-desktop.json` → réglages → Développeur →
Modifier la config. **Claude Code** : `{CLAUDE_CODE}`. **Cursor** :
`mcp/cursor.json` → `.cursor/mcp.json`. **Docker** : `mcp/docker.json`.
Dans ces trois-là, mettez le chemin complet de `leka-architect` (celui du `.venv`).

## 5. Avec un LLM sans outils (ChatGPT, Copilot chat…)

Le pack de prompts est dans `prompts/` (ou `leka-architect prompts`) : les
consignes, le mode d'emploi pour joindre les pages exportées, le schéma du deck.

## Confidentialité

- Lecture seule sur Confluence.
- Les pages ne vont qu'au modèle configuré ; aucun appel à LEKA, aucune
  télémétrie.
- Aucun secret dans ce paquet : vos identifiants restent dans votre `.env`.
- Les fichiers de Connaissances ne sont lus que dans leur dossier.
"""


__all__ = [
    "CLAUDE_CODE",
    "DOCKERFILE",
    "ENV_EXAMPLE",
    "MCP",
    "PYPROJECT",
    "README",
    "copilot_prompt",
    "prompt_pack",
]
