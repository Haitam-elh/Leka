"""The copy tool for Windows, in one click (2026-10-25): a zip to unpack and
double-click — Python included (python.org's embeddable build: nothing to
install, no administrator rights), the tool, Copier-Confluence.bat, a
LISEZ-MOI.txt, and the Confluence to copy into already written in its .env.

    python3 build_windows.py --target-url https://site.atlassian.net \\
        --target-email moi@exemple.com [--ask-token] [--out ~/Desktop]

    --ask-token   the target's API token asked (hidden) and put in the .env:
                  the person who copies is then asked nothing about it.
                  Without it, they are asked for it.

The person who copies is asked only for their own Confluence: its address,
their e-mail, their token. Their token is never written anywhere.
"""

from __future__ import annotations

import argparse
import getpass
import io
import sys
import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
PYTHON = "3.13.9"
EMBEDDED = f"https://www.python.org/ftp/python/{PYTHON}/python-{PYTHON}-embed-amd64.zip"
ROOT = "copie-confluence"

LAUNCHER = """@echo off
rem Copie Confluence : double-cliquez. Une fenetre s'ouvre et pose quelques questions.
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
cd /d "%~dp0"
"%~dp0python\\python.exe" "%~dp0confluence_copy.py" %*
echo.
pause
"""

README = """COPIE CONFLUENCE — mode d'emploi (5 minutes)

1. Clic droit sur le fichier zip → « Extraire tout… » → Extraire.
   (Ne lancez rien depuis l'intérieur du zip : extrayez d'abord.)

2. Dans le dossier extrait, double-cliquez sur « Copier-Confluence ».
   Si Windows affiche « Windows a protégé votre ordinateur » :
   « Informations complémentaires » → « Exécuter quand même ».

3. Répondez aux questions :
   - l'adresse de votre Confluence (ex. https://votre-entreprise.atlassian.net) ;
   - votre adresse e-mail ;
   - votre token API : créez-le ici, en une minute :
     https://id.atlassian.com/manage-profile/security/api-tokens
     (« Créer un token d'API », copiez-le, puis collez-le dans la fenêtre :
     rien ne s'affiche quand vous collez, c'est normal, appuyez sur Entrée) ;
   - les espaces à copier : des numéros, ou Entrée pour tous.

4. Attendez « Copie terminée ». Tout est copié : les pages, leur
   arborescence, leurs pièces jointes (PDF, Excel, images…).

Votre Confluence n'est que lu : rien n'y est modifié. Votre token n'est
écrit nulle part. Relancer ne crée pas de doublons.
"""


def embedded(cache: Path) -> bytes:
    """python.org's embeddable Python for Windows — downloaded once."""
    kept = cache / f"python-{PYTHON}-embed-amd64.zip"
    if not kept.is_file():
        cache.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(EMBEDDED, timeout=120) as answer:
            kept.write_bytes(answer.read())
    return kept.read_bytes()


def env_of(target_url: str, target_email: str, target_token: str) -> str:
    return (
        "# Le Confluence où copier — déjà renseigné. Ne pas modifier.\n"
        f"TARGET_URL={target_url}\n"
        f"TARGET_EMAIL={target_email}\n"
        f"TARGET_TOKEN={target_token}\n"
        "\n"
        "# Votre Confluence : l'assistant vous le demande. Rien à écrire ici.\n"
    )


def bundle(python: bytes, *, target_url: str, target_email: str, target_token: str = "") -> bytes:
    """The zip: Python, the tool, its launcher, its instructions, its .env."""
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zipped:
        with zipfile.ZipFile(io.BytesIO(python)) as runtime:
            for name in runtime.namelist():
                zipped.writestr(f"{ROOT}/python/{name}", runtime.read(name))
        zipped.writestr(f"{ROOT}/confluence_copy.py", (HERE / "confluence_copy.py").read_bytes())
        zipped.writestr(f"{ROOT}/Copier-Confluence.bat", LAUNCHER.replace("\n", "\r\n"))
        zipped.writestr(f"{ROOT}/LISEZ-MOI.txt", README.replace("\n", "\r\n").encode("utf-8-sig"))
        zipped.writestr(f"{ROOT}/.env", env_of(target_url, target_email, target_token))
    return out.getvalue()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--target-url", required=True)
    parser.add_argument("--target-email", required=True)
    parser.add_argument("--ask-token", action="store_true", help="put the target's token in it")
    parser.add_argument("--out", default=str(Path.home() / "Desktop"))
    parser.add_argument("--python-zip", help="an embeddable Python zip already downloaded")
    parser.add_argument("--cache", default=str(Path.home() / ".cache" / "leka-confluence-copy"))
    args = parser.parse_args(argv)
    token = ""
    if args.ask_token:
        token = getpass.getpass("Token API du Confluence où copier (rien ne s'affiche) : ").strip()
        if not token:
            print("Aucun token : le paquet le demandera à la personne qui copie.")
    python = Path(args.python_zip).read_bytes() if args.python_zip else embedded(Path(args.cache))
    out = Path(args.out).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    target = out / "Copie-Confluence-Windows.zip"
    target.write_bytes(
        bundle(
            python, target_url=args.target_url, target_email=args.target_email, target_token=token
        )
    )
    print(target)
    return 0


if __name__ == "__main__":
    sys.exit(main())
