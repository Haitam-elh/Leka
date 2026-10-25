"""What ships with the downloadable architect, besides its code: its README,
its .env.example, its Dockerfile, its MCP configurations — one per client —
and its prompt pack for models without tools. Written here, from the same
prompts and sections as the code, so the pack never says other than the
agent does.
"""

from __future__ import annotations

import json

from . import __version__
from .model import ELEMENT_TYPES, RELATION_TYPES, SCHEMA, SECTIONS
from .prompts import SYSTEM

PYPROJECT = f"""[build-system]
requires = ["setuptools>=61"]
build-backend = "setuptools.build_meta"

[project]
name = "leka-architect"
version = "{__version__}"
description = "L'Architecte applicatif de LEKA : Confluence vers un dossier d'architecture ArchiMate (Markdown, PDF, Word), sur votre LLM."
readme = "README.md"
requires-python = ">=3.9"
dependencies = ["reportlab>=3.6"]

[project.scripts]
leka-architect = "leka_architect.cli:main"

[tool.setuptools]
packages = ["leka_architect"]
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
    "vscode-copilot.json": {
        "servers": {
            "leka-architect": {
                "type": "stdio",
                "command": "leka-architect",
                "args": ["mcp"],
                "envFile": "${workspaceFolder}/.env",
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


def prompt_pack() -> dict[str, str]:
    """For a chat model without tools — ChatGPT, Copilot chat: its
    instructions, the dossier's template, and how to give it the pages."""
    sections = "\n".join(f"{n}. {title} (`{key}`)" for n, (key, title) in enumerate(SECTIONS, 1))
    types = "\n".join(
        f"- **{layer}** : {', '.join(kinds)}" for layer, kinds in ELEMENT_TYPES.items()
    )
    return {
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

1. **Les pages.** Depuis Confluence (Paramètres de l'espace → Exporter l'espace,
   en HTML), ou par l'API :

       leka-architect pages --space ARCHI --output pages.md

   `pages.md` contient chaque page avec son identifiant entre crochets, sa
   place dans l'arborescence et son texte : c'est ce que le modèle cite.

2. **Les consignes.** Collez `instructions-systeme.md` en instructions
   personnalisées (ou en premier message).

3. **La demande.** Joignez `pages.md` (ou collez-le en plusieurs messages s'il
   est long) et demandez : « Produis le dossier d'architecture en JSON, selon
   le schéma ».

4. **Le livrable.** Enregistrez la réponse dans `reponse.json`, puis :

       leka-architect render --dossier reponse.json --space ARCHI --output rapport

   Le Markdown, le PDF et le Word sont écrits dans `rapport/`, chaque page
   citée vérifiée — une page qui n'existe pas est écartée et signalée.
""",
    }


README = f"""# L'Architecte applicatif — version installable (v{__version__})

Il lit votre Confluence et produit le **dossier d'architecture applicative
structuré ArchiMate 3.1** — couches métier, application et technologie,
flux, dépendances, points à confirmer —, **chaque section citant les pages
Confluence** dont elle est tirée. En Markdown, PDF et Word.

C'est le même agent que dans LEKA : les mêmes consignes, les mêmes étapes,
le même livrable. **Rien ne passe par LEKA** : vos pages vont au modèle que
vous configurez, et nulle part ailleurs. Aucune télémétrie.

## 1. Installer (moins de 10 minutes)

Python 3.9 ou plus :

    pip install ./leka-architect          # le dossier de ce paquet

Ou avec Docker :

    docker build -t leka-architect ./leka-architect

## 2. Configurer

    cp .env.example .env

Remplissez `.env` :

- **Confluence** : son adresse, l'adresse e-mail du compte et un token API
  (Cloud), ou un token d'accès personnel (Data Center). Lecture seule : rien
  n'est jamais écrit dans Confluence. Un export sur disque marche aussi
  (`ARCHITECT_CONFLUENCE_EXPORT`).
- **Le modèle** :
  - Azure OpenAI : `ARCHITECT_LLM_PROVIDER=azure`, le nom du déploiement dans
    `ARCHITECT_LLM_MODEL`, `ARCHITECT_LLM_BASE_URL=https://<ressource>.openai.azure.com`,
    `ARCHITECT_LLM_API_VERSION`, la clé.
  - Claude : `ARCHITECT_LLM_PROVIDER=anthropic`, `ARCHITECT_LLM_MODEL=claude-sonnet-5`, la clé.
  - Toute API compatible OpenAI (OpenAI, Mistral, Ollama, vLLM, LM Studio, un
    LLM interne) : `ARCHITECT_LLM_PROVIDER=openai`, son adresse dans
    `ARCHITECT_LLM_BASE_URL`, son modèle.

Vérifiez ce qu'il lit :

    leka-architect tree --space ARCHI

## 3. Lancer la simulation

    leka-architect simulate --space ARCHI --output ./rapport
    leka-architect simulate --space ARCHI --root-page 123456 --focus "Facturation" --output ./rapport

Dans `./rapport` :

    dossier-architecture.md     le dossier, chaque page citée en lien
    dossier-architecture.pdf
    dossier-architecture.docx
    dossier-architecture.json   le dossier lui-même (pour comparer, réécrire)

Pour comparer à un document de référence (Word, Markdown, HTML ou texte) :

    leka-architect compare --dossier ./rapport --reference reference.docx --output ./rapport

## 4. Dans Copilot, Claude ou Cursor (MCP)

    leka-architect mcp

expose quatre outils : `list_confluence_tree`, `read_confluence_page`,
`analyze_architecture`, `generate_architecture_document`, et la consigne
`architecte`. Configurations prêtes à coller, dans `mcp/` :

- **GitHub Copilot dans VS Code** (mode agent) : `mcp/vscode-copilot.json` →
  `.vscode/mcp.json` de votre projet (il lit le `.env` du projet). Puis, dans
  le chat Copilot en mode agent : « Génère la doc d'architecture de l'espace
  ARCHI ».
- **Claude Desktop** : `mcp/claude-desktop.json` → réglages → Développeur →
  Modifier la config.
- **Claude Code** : `{CLAUDE_CODE}`
- **Cursor** : `mcp/cursor.json` → `.cursor/mcp.json`.
- **Docker** : `mcp/docker.json`.

Sans modèle configuré dans `.env`, c'est le modèle du client (Copilot,
Claude…) qui rédige le dossier : `analyze_architecture` lui donne les pages et
les consignes, `generate_architecture_document` écrit ses fichiers.

## 5. Avec un LLM sans outils (ChatGPT, Copilot chat…)

Le pack de prompts est dans `prompts/` (ou `leka-architect prompts`) : les
instructions système, le modèle du livrable, le mode d'emploi pour joindre les
pages exportées.

## Exemple de sortie

    # Dossier d'architecture — Facturation
    *Espace Confluence ARCHI*

    ## 3. Couche application
    Billing API reçoit les commandes et écrit dans Ledger.

    | Type | Élément | Description | Statut | Sources |
    |---|---|---|---|---|
    | Composant applicatif | Billing API | Expose /invoices. | Documenté | [Billing API](https://…/pages/102) |

    **Sources :** [Applications](https://…/pages/101), [Billing API](https://…/pages/102)

## Confidentialité

- Lecture seule sur Confluence.
- Les pages ne vont qu'au modèle configuré ; aucun appel à LEKA, aucune
  télémétrie.
- Aucun secret dans ce paquet : vos identifiants restent dans votre `.env`.
"""


__all__ = ["CLAUDE_CODE", "DOCKERFILE", "ENV_EXAMPLE", "MCP", "PYPROJECT", "README", "prompt_pack"]
