"""Native SuperQode management commands for the optional Tau harness."""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path

from .tau_adapter import tau_installation_status


@dataclass(frozen=True)
class TauProviderSummary:
    """Safe, non-secret Tau provider information for the TUI."""

    name: str
    display_name: str
    kind: str
    base_url: str
    models: tuple[str, ...]
    default_model: str
    authenticated: bool
    is_default: bool


def _tau_paths(tau_home: Path | None = None):
    from tau_coding.paths import TauPaths

    return TauPaths(home=tau_home) if tau_home is not None else TauPaths()


def _require_tau() -> None:
    available, issue = tau_installation_status()
    if not available:
        raise RuntimeError(issue)


def list_tau_providers(*, tau_home: Path | None = None) -> list[TauProviderSummary]:
    """List Tau providers without exposing their stored credentials."""
    _require_tau()
    from tau_coding.catalog_loader import effective_catalog
    from tau_coding.credentials import FileCredentialStore, credentials_path
    from tau_coding.provider_config import load_provider_settings, provider_kind

    paths = _tau_paths(tau_home)
    settings = load_provider_settings(paths)
    display_names = {entry.name: entry.display_name for entry in effective_catalog(paths)}
    credentials = FileCredentialStore(credentials_path(paths))
    summaries: list[TauProviderSummary] = []
    for provider in settings.providers:
        credential_name = str(getattr(provider, "credential_name", "") or provider.name)
        api_key_env = str(getattr(provider, "api_key_env", "") or "")
        authenticated = bool(
            credentials.get(credential_name)
            or credentials.get_oauth(credential_name)
            or (api_key_env and os.environ.get(api_key_env))
        )
        summaries.append(
            TauProviderSummary(
                name=provider.name,
                display_name=display_names.get(provider.name, provider.name),
                kind=provider_kind(provider),
                base_url=str(getattr(provider, "base_url", "") or ""),
                models=tuple(provider.models),
                default_model=str(provider.default_model or ""),
                authenticated=authenticated,
                is_default=provider.name == settings.default_provider,
            )
        )
    return summaries


def configure_tau_provider(
    *,
    provider_name: str,
    display_name: str,
    model: str,
    base_url: str | None,
    api_key_env: str,
    credential: str,
    docs_url: str = "",
    tau_home: Path | None = None,
) -> TauProviderSummary:
    """Copy one SuperQode route into Tau and make it the active Tau route."""
    _require_tau()
    from tau_coding.catalog_loader import effective_catalog, save_user_catalog_entries
    from tau_coding.credentials import FileCredentialStore, credentials_path
    from tau_coding.provider_catalog import ProviderCatalogEntry
    from tau_coding.provider_config import (
        OpenAICompatibleProviderConfig,
        load_provider_settings,
        provider_kind,
        save_provider_settings,
        upsert_openai_compatible_provider,
        upsert_provider,
    )

    name = provider_name.strip()
    selected_model = model.strip()
    if not name:
        raise ValueError("Tau provider name must not be empty")
    if not selected_model:
        raise ValueError("Tau model must not be empty")

    paths = _tau_paths(tau_home)
    settings = load_provider_settings(paths)
    existing = next((item for item in settings.providers if item.name == name), None)
    models = tuple(
        dict.fromkeys((selected_model, *(tuple(existing.models) if existing is not None else ())))
    )

    if existing is not None:
        provider = replace(existing, models=models, default_model=selected_model)
        updated = upsert_provider(settings, provider, set_default=True)
    else:
        endpoint = str(base_url or "").strip().rstrip("/")
        if not endpoint:
            raise ValueError(
                f"Tau provider {name!r} is not built in and needs an OpenAI-compatible base URL"
            )
        provider = OpenAICompatibleProviderConfig(
            name=name,
            base_url=endpoint,
            api_key_env=api_key_env,
            credential_name=name,
            models=models,
            default_model=selected_model,
        )
        entry = ProviderCatalogEntry(
            name=name,
            display_name=display_name.strip() or name,
            kind="openai-compatible",
            base_url=endpoint,
            api_key_env=api_key_env,
            credential_name=name,
            models=models,
            default_model=selected_model,
            docs_url=docs_url or endpoint,
        )
        save_user_catalog_entries((entry,), paths)
        updated = upsert_openai_compatible_provider(settings, provider, set_default=True)

    save_provider_settings(updated, paths)
    credential_name = str(getattr(provider, "credential_name", "") or name)
    FileCredentialStore(credentials_path(paths)).set(credential_name, credential)
    display_names = {entry.name: entry.display_name for entry in effective_catalog(paths)}
    return TauProviderSummary(
        name=name,
        display_name=display_names.get(name, display_name.strip() or name),
        kind=provider_kind(provider),
        base_url=str(getattr(provider, "base_url", "") or ""),
        models=tuple(provider.models),
        default_model=selected_model,
        authenticated=True,
        is_default=True,
    )


def select_tau_model(
    provider_name: str,
    model: str,
    *,
    tau_home: Path | None = None,
) -> TauProviderSummary:
    """Persist Tau's default provider and model selection."""
    _require_tau()
    from tau_coding.provider_config import (
        load_provider_settings,
        save_provider_settings,
        set_default_provider_model,
    )

    paths = _tau_paths(tau_home)
    settings = load_provider_settings(paths)
    updated = set_default_provider_model(
        settings,
        provider_name=provider_name.strip(),
        model=model.strip(),
    )
    save_provider_settings(updated, paths)
    return next(
        provider
        for provider in list_tau_providers(tau_home=tau_home)
        if provider.name == provider_name.strip()
    )


def delete_tau_credential(provider_name: str, *, tau_home: Path | None = None) -> None:
    """Remove a Tau provider credential without changing SuperQode authentication."""
    _require_tau()
    from tau_coding.credentials import FileCredentialStore, credentials_path
    from tau_coding.provider_config import load_provider_settings

    paths = _tau_paths(tau_home)
    settings = load_provider_settings(paths)
    provider = settings.get_provider(provider_name.strip())
    credential_name = str(getattr(provider, "credential_name", "") or provider.name)
    FileCredentialStore(credentials_path(paths)).delete(credential_name)


__all__ = [
    "TauProviderSummary",
    "configure_tau_provider",
    "delete_tau_credential",
    "list_tau_providers",
    "select_tau_model",
]
