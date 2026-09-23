"""Which connectors exist: an explicit dictionary, filled by a decorator.

No discovery. A connector exists because leka/connectors/__init__.py
imports its package and the package's class carries @register_connector —
two lines anyone can read, grep and review. Plugins loaded from a directory
or an entry point would make "what code runs against a customer's GitHub?"
a question answered at runtime (see docs/adr/015-connector-framework.md).
"""

from __future__ import annotations

from typing import Any

from leka.connectors.base import Connector, ConnectorManifest
from leka.connectors.models import SourceKind

_REGISTRY: dict[SourceKind, type[Connector[Any, Any]]] = {}


class UnknownConnectorError(LookupError):
    """No connector is registered for this kind."""


def register_connector[C: type[Connector[Any, Any]]](cls: C) -> C:
    key = cls.manifest.key
    if key in _REGISTRY and _REGISTRY[key] is not cls:
        msg = f"two connectors claim {key!r}: {_REGISTRY[key].__name__} and {cls.__name__}"
        raise ValueError(msg)
    _REGISTRY[key] = cls
    return cls


def unregister_connector(key: SourceKind) -> None:
    """For tests that register a connector of their own."""
    _REGISTRY.pop(key, None)


def get_connector(key: SourceKind | str) -> type[Connector[Any, Any]]:
    try:
        return _REGISTRY[SourceKind(key)]
    except (KeyError, ValueError) as error:
        msg = f"no connector for {key!r}"
        raise UnknownConnectorError(msg) from error


def manifests() -> list[ConnectorManifest]:
    return [cls.manifest for cls in sorted(_REGISTRY.values(), key=lambda c: c.manifest.key)]
