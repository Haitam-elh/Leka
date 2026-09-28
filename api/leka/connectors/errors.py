"""What went wrong with a source, said the same way whatever the vendor.

Every connector translates its vendor's failures into one Diagnostic: a
stable code a program can branch on, whether retrying makes sense, and two
sentences for the admin who reads it — what happened, and what to do. The
screen, the API, the health job and the stored `last_error` all carry the
same object, so "why is GitHub red?" has one answer wherever it is asked.

NOTHING SECRET CROSSES THIS LINE. A vendor's error body can quote the
request; `detail` is cleaned of any configured secret and of anything that
looks like a token or an Authorization header before a Diagnostic exists.
"""

from __future__ import annotations

import enum
import re
from collections.abc import Iterable

from pydantic import BaseModel, ConfigDict, Field


class DiagnosticCode(enum.StrEnum):
    AUTH_INVALID = "AUTH_INVALID"
    AUTH_EXPIRED = "AUTH_EXPIRED"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    INSUFFICIENT_SCOPE = "INSUFFICIENT_SCOPE"
    NOT_FOUND = "NOT_FOUND"
    RATE_LIMITED = "RATE_LIMITED"
    TIMEOUT = "TIMEOUT"
    NETWORK_UNREACHABLE = "NETWORK_UNREACHABLE"
    PROVIDER_ERROR = "PROVIDER_ERROR"
    CONFIG_INVALID = "CONFIG_INVALID"
    UNKNOWN = "UNKNOWN"


class Diagnostic(BaseModel):
    """One failure, standardised. Stored as `sources.last_error`."""

    model_config = ConfigDict(frozen=True)

    code: DiagnosticCode
    retryable: bool
    retry_after: int | None = Field(default=None, description="Seconds, when the vendor said.")
    message: str = Field(description="What happened, for an admin.")
    remediation: str = Field(description="What to do about it.")
    provider_status: int | None = Field(default=None, description="The vendor's HTTP status.")
    detail: str | None = Field(default=None, description="Technical detail, cleaned of secrets.")


class ConnectorError(Exception):
    """Raised by a connector; carries the Diagnostic and nothing else."""

    def __init__(self, diagnostic: Diagnostic) -> None:
        super().__init__(f"{diagnostic.code}: {diagnostic.message}")
        self.diagnostic = diagnostic


# (message, remediation, retryable) — the admin reads these, in French, the
# language of the product. A connector may say something more specific with
# `message=`; it never has to invent the remediation.
_WORDING: dict[DiagnosticCode, tuple[str, str, bool]] = {
    DiagnosticCode.AUTH_INVALID: (
        "Le token a été refusé par le fournisseur.",
        "Vérifiez qu'il a été copié en entier, puis remplacez les identifiants.",
        False,
    ),
    DiagnosticCode.AUTH_EXPIRED: (
        "Le token a expiré.",
        "Générez-en un nouveau chez le fournisseur et remplacez les identifiants.",
        False,
    ),
    DiagnosticCode.PERMISSION_DENIED: (
        "Le fournisseur refuse l'accès à cette ressource.",
        "Vérifiez que le compte du token a accès à l'organisation et aux dépôts visés.",
        False,
    ),
    DiagnosticCode.INSUFFICIENT_SCOPE: (
        "Le token n'a pas les permissions nécessaires.",
        "Ajoutez les permissions de lecture demandées au token, puis relancez le test.",
        False,
    ),
    DiagnosticCode.NOT_FOUND: (
        "La ressource configurée n'existe pas, ou n'est pas visible avec ce token.",
        "Vérifiez le nom configuré (organisation, projet…) et la visibilité du token.",
        False,
    ),
    DiagnosticCode.RATE_LIMITED: (
        "Le quota d'appels du fournisseur est épuisé.",
        "Patientez jusqu'au renouvellement du quota ; LEKA réessaiera.",
        True,
    ),
    DiagnosticCode.TIMEOUT: (
        "Le fournisseur n'a pas répondu à temps.",
        "Réessayez dans quelques minutes. Si cela persiste, vérifiez l'adresse configurée.",
        True,
    ),
    DiagnosticCode.NETWORK_UNREACHABLE: (
        "Le fournisseur est injoignable.",
        "Vérifiez l'adresse configurée et que le service est accessible depuis Internet.",
        True,
    ),
    DiagnosticCode.PROVIDER_ERROR: (
        "Le fournisseur a rencontré une erreur de son côté.",
        "Réessayez plus tard ; consultez la page de statut du fournisseur si cela dure.",
        True,
    ),
    DiagnosticCode.CONFIG_INVALID: (
        "La configuration de la source est invalide.",
        "Corrigez les champs signalés, puis relancez le test.",
        False,
    ),
    DiagnosticCode.UNKNOWN: (
        "Une erreur inattendue est survenue.",
        "Relancez le test. Si l'erreur persiste, transmettez le détail au support LEKA.",
        True,
    ),
}

# Shapes of credentials that must never survive into `detail`, whether or not
# they are this source's: a vendor may echo someone else's.
_TOKEN_SHAPES = re.compile(
    r"(?i)(authorization\s*[:=]\s*\S+(\s+\S+)?)"
    r"|(bearer\s+\S+)"
    r"|(token\s+[A-Za-z0-9_\-.]{8,})"
    r"|(github_pat_[A-Za-z0-9_]+)"
    r"|(gh[pousr]_[A-Za-z0-9]+)"
    # GitLab's prefixed tokens: personal, OAuth, deploy, runner, CI job…
    r"|(gl(?:pat|oas|dt|rt|cbt|ptt|ft|imt|soat|ffct|agent)-[A-Za-z0-9_\-]{10,})"
    # Atlassian's: API tokens, access tokens, the retired app passwords.
    r"|(AT(?:ATT|CTT|BB)[A-Za-z0-9_\-=]{16,})"
    # A private key in PEM, however its newlines were escaped by the JSON it
    # was echoed in — to its end, or to the end of the text when cut short.
    r"|(-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|$))"
    # Linear's personal API keys and OAuth tokens.
    r"|(lin_(?:api|oauth)_[A-Za-z0-9]{16,})"
    # Notion's integration secrets, the current prefix and the retired one.
    r"|((?:ntn|secret)_[A-Za-z0-9]{32,})"
    # Asana's personal access tokens: "2/1204…/1209…:9f3c…".
    r"|(\b[0-9]/[0-9]{6,}(?:/[0-9]{6,})?:[0-9a-f]{32}\b)"
    # Trello's tokens, and ClickUp's personal ones.
    r"|(ATTA[A-Fa-f0-9]{60,})"
    r"|(pk_[0-9]+_[A-Za-z0-9]{20,})"
    # A JSON Web Token — Monday's API tokens are one — whoever issued it.
    r"|(eyJ[A-Za-z0-9_\-]{8,}\.eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,})"
)
REDACTED = "[redacted]"
MAX_DETAIL = 300


def sanitise(text: str, secrets: Iterable[str] = ()) -> str:
    """`text` with every given secret and every token-shaped string removed."""
    for secret in secrets:
        if secret:
            text = text.replace(secret, REDACTED)
    text = _TOKEN_SHAPES.sub(REDACTED, text)
    return text[:MAX_DETAIL]


def diagnose(
    code: DiagnosticCode,
    *,
    message: str | None = None,
    provider_status: int | None = None,
    retry_after: int | None = None,
    detail: str | None = None,
    secrets: Iterable[str] = (),
) -> ConnectorError:
    """Build the error a connector raises. `secrets` are removed from `detail`."""
    default_message, remediation, retryable = _WORDING[code]
    return ConnectorError(
        Diagnostic(
            code=code,
            retryable=retryable,
            retry_after=retry_after,
            message=message or default_message,
            remediation=remediation,
            provider_status=provider_status,
            detail=sanitise(detail, secrets) if detail else None,
        )
    )
