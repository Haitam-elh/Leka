"""Connectors: one subpackage per customer system, plus the framework they share.

Bottom of the dependency chain. Depends on leka.core, leka.db and
leka.platform — never on ingestion, knowledge, context or intentions
(architecture rule 1).

A connector's job stops at fetching. It does not interpret, normalise or
store: that is leka.ingestion. See docs/connectors/framework.md.

THE REGISTRY IS THIS FILE. A connector exists because its package is
imported below; there is no other discovery (ADR 015).
"""

from leka.connectors import (
    aws,  # noqa: F401  — registers AwsConnector
    azure,  # noqa: F401  — registers AzureConnector
    bitbucket,  # noqa: F401  — registers BitbucketConnector
    confluence,  # noqa: F401  — registers ConfluenceConnector
    gcp,  # noqa: F401  — registers GcpConnector
    github,  # noqa: F401  — registers GitHubConnector
    gitlab,  # noqa: F401  — registers GitLabConnector
    jira,  # noqa: F401  — registers JiraConnector
    linear,  # noqa: F401  — registers LinearConnector
    notion,  # noqa: F401  — registers NotionConnector
)
from leka.connectors.base import (
    Capability,
    ConnectionTestResult,
    Connector,
    ConnectorCategory,
    ConnectorManifest,
    HealthResult,
    ScopeListing,
    ScopeOption,
)
from leka.connectors.errors import ConnectorError, Diagnostic, DiagnosticCode, diagnose
from leka.connectors.health import run_health_check
from leka.connectors.lifecycle import InvalidTransitionError, LifecycleEvent, next_status
from leka.connectors.models import (
    HealthStatus,
    Source,
    SourceCredential,
    SourceEvent,
    SourceEventType,
    SourceKind,
    SourceSettingsVersion,
    SourceStatus,
    SyncStatus,
)
from leka.connectors.registry import (
    UnknownConnectorError,
    get_connector,
    manifests,
    register_connector,
    unregister_connector,
)
from leka.connectors.repository import SourceCredentialSweeper, SourceRepository
from leka.connectors.schemas import (
    CatalogEntry,
    CredentialsRead,
    CredentialsUpdate,
    HealthRead,
    RawRecord,
    ScopeOptionsRead,
    SettingsCheck,
    SettingsSaved,
    SettingsVersionRead,
    SourceCreate,
    SourceEventRead,
    SourceRead,
    SourceSettingsRead,
    SourceTestOutcome,
    SourceUpdate,
    SyncResult,
)
from leka.connectors.secrets import DatabaseFernetSecretStore, SecretStore, StoredCredentials
from leka.connectors.service import (
    ActivationRefusedError,
    DuplicateSourceError,
    InvalidSettingsError,
    InvalidSourceInputError,
    NoScopeError,
    SettingsConflictError,
    SourceNotFoundError,
    SourceService,
)
from leka.connectors.settings import (
    Finding,
    Mapping,
    ScopeRules,
    SourceSettings,
    first_match,
    in_scope,
)
from leka.connectors.tasks import (
    ROTATED_COLUMNS,
    RotationRefusedError,
    RotationReport,
    rotate_source_credentials,
)

__all__ = [
    "ROTATED_COLUMNS",
    "ActivationRefusedError",
    "Capability",
    "CatalogEntry",
    "ConnectionTestResult",
    "Connector",
    "ConnectorCategory",
    "ConnectorError",
    "ConnectorManifest",
    "CredentialsRead",
    "CredentialsUpdate",
    "DatabaseFernetSecretStore",
    "Diagnostic",
    "DiagnosticCode",
    "DuplicateSourceError",
    "Finding",
    "HealthRead",
    "HealthResult",
    "HealthStatus",
    "InvalidSettingsError",
    "InvalidSourceInputError",
    "InvalidTransitionError",
    "LifecycleEvent",
    "Mapping",
    "NoScopeError",
    "RawRecord",
    "RotationRefusedError",
    "RotationReport",
    "ScopeListing",
    "ScopeOption",
    "ScopeOptionsRead",
    "ScopeRules",
    "SecretStore",
    "SettingsCheck",
    "SettingsConflictError",
    "SettingsSaved",
    "SettingsVersionRead",
    "Source",
    "SourceCreate",
    "SourceCredential",
    "SourceCredentialSweeper",
    "SourceEvent",
    "SourceEventRead",
    "SourceEventType",
    "SourceKind",
    "SourceNotFoundError",
    "SourceRead",
    "SourceRepository",
    "SourceService",
    "SourceSettings",
    "SourceSettingsRead",
    "SourceSettingsVersion",
    "SourceStatus",
    "SourceTestOutcome",
    "SourceUpdate",
    "StoredCredentials",
    "SyncResult",
    "SyncStatus",
    "UnknownConnectorError",
    "diagnose",
    "first_match",
    "get_connector",
    "in_scope",
    "manifests",
    "next_status",
    "register_connector",
    "rotate_source_credentials",
    "run_health_check",
    "unregister_connector",
]
