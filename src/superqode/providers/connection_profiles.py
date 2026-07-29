"""Connection profiles — the product/account-level choices in ``:connect``.

A *connection source* is what the user is connecting SuperQode to (a vendor
subscription, a BYOK provider, a local model, an ACP agent). Each
profile declares a ``connector`` that the TUI/CLI dispatches on:

    runtime      self-contained runtime (own model+auth), e.g. codex-sdk
    copilot      one Copilot subscription entry with SDK/CLI route selection
    acp          a specific ACP agent by short_name, e.g. "claude" or "grok"
    byok         the BYOK provider/model picker, optionally pinned to one provider
    local        the local provider/model picker
    acp-picker   the generic "pick any ACP agent" list
    harness-picker optional non-ACP harness integrations
    subscription-picker vendor plans authenticated by their own local CLI/OAuth state
    external-cli a local vendor TUI that does not expose ACP/headless events yet

Profiles are grouped into **menus** so the first screen a new user sees stays
short. ``root`` holds the five ways to connect (local, ACP, BYOK, subscriptions,
other harnesses); ``subscriptions`` holds the vendor coding agents you sign in
to. Every profile stays directly reachable by id (``:connect codex``) regardless
of which menu shows it.

API-key-only products do not belong in the subscription menu. They are reached
through BYOK or an explicit runtime command instead.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional

from .env_introspect import missing_extra_hint


#: The two ``:connect`` screens. ``root`` is what opens by default.
CONNECT_MENU_ROOT = "root"
CONNECT_MENU_SUBSCRIPTIONS = "subscriptions"
CONNECT_MENUS = (CONNECT_MENU_ROOT, CONNECT_MENU_SUBSCRIPTIONS)


@dataclass(frozen=True)
class ConnectionProfile:
    """A product/account-level connection source shown in ``:connect``."""

    id: str
    label: str
    description: str
    connector: str  # runtime | copilot | acp | byok | local | pickers | external-cli
    group: str = ""
    menu: str = CONNECT_MENU_ROOT
    runtime: Optional[str] = None  # for connector == "runtime"
    acp_agent: Optional[str] = None  # for connector == "acp"
    byok_provider: Optional[str] = None  # for connector == "byok"
    self_contained: bool = False
    # Probe (no network) for whether this source is ready to use right now.
    detect: Optional[Callable[[], bool]] = None
    # Shown when detect() is False, to tell the user how to enable it.
    unavailable_hint: str = ""

    @property
    def available(self) -> bool:
        if self.detect is None:
            return True
        try:
            return bool(self.detect())
        except Exception:  # noqa: BLE001 - availability probes must never raise
            return False


# --- availability probes (cheap, local-only) ---------------------------------


def _codex_ready() -> bool:
    """codex-sdk extra installed AND a local Codex login present."""
    if importlib.util.find_spec("openai_codex") is None:
        return False
    return (Path.home() / ".codex" / "auth.json").exists()


def _copilot_sdk_ready() -> bool:
    """The optional official GitHub Copilot SDK is importable."""
    try:
        return importlib.util.find_spec("copilot") is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def _copilot_acp_ready() -> bool:
    """The GitHub Copilot CLI needed for the ACP route is on PATH."""
    return shutil.which("copilot") is not None


def _copilot_subscription_ready() -> bool:
    """At least one supported Copilot subscription integration is installed."""
    return _copilot_sdk_ready() or _copilot_acp_ready()


def _kimi_code_ready() -> bool:
    """Moonshot AI's official Kimi Code CLI is available for ACP."""
    return shutil.which("kimi") is not None


def _qwen_code_ready() -> bool:
    """QwenLM's official Qwen Code CLI is available for ACP."""
    return shutil.which("qwen") is not None


def _antigravity_cli_ready() -> bool:
    """The CLI exists and meets the minimum safe subprocess version."""
    from superqode.runtime.antigravity_status import probe_antigravity_cli

    return probe_antigravity_cli().compatible


def _glm_cli_ready() -> bool:
    """The GLM ACP agent CLI is on PATH."""
    return shutil.which("glm-acp-agent") is not None


def _devin_cli_ready() -> bool:
    """Cognition's Devin CLI is installed (it owns its own sign-in)."""
    return shutil.which("devin") is not None


def _cursor_cli_ready() -> bool:
    """Cursor Agent CLI is installed; Cursor owns its local account login."""
    return shutil.which("cursor-agent") is not None


def _amp_cli_ready() -> bool:
    """Amp and its ACP adapter are installed; Amp owns account authentication."""
    return shutil.which("amp") is not None and shutil.which("acp-amp") is not None


def _droid_cli_ready() -> bool:
    """Factory Droid is installed; the CLI owns its account authentication."""
    return shutil.which("droid") is not None


def _kiro_cli_ready() -> bool:
    """Kiro CLI is installed; its OAuth/IAM login remains vendor-managed."""
    return shutil.which("kiro-cli") is not None


def _grok_cli_ready() -> bool:
    """Official Grok CLI installed with a locally managed subscription login."""
    return shutil.which("grok") is not None and (Path.home() / ".grok" / "auth.json").exists()


def _zai_ready() -> bool:
    """A first-party Z.AI general-API key is available locally."""
    from .credentials import provider_api_key
    from .registry import PROVIDERS

    return bool(provider_api_key(PROVIDERS["zai"]))


_BYOK_KEY_ENVS = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "GROQ_API_KEY",
    "MISTRAL_API_KEY",
    "OPENROUTER_API_KEY",
    "XAI_API_KEY",
    "ZAI_API_KEY",
)


def _byok_ready() -> bool:
    return any(os.environ.get(env) for env in _BYOK_KEY_ENVS)


# --- registry -----------------------------------------------------------------

# The root menu is deliberately five entries: the three ways SuperQode itself
# can drive a model, the vendor-subscription submenu, and the optional
# harnesses. A subscription entry must use an existing vendor plan through the
# vendor's local CLI/OAuth state; API-key-only routes stay under BYOK.
_ROOT_PROFILES: List[ConnectionProfile] = [
    ConnectionProfile(
        id="local",
        label="Local",
        description="Run models on your own machine: Ollama / LM Studio / MLX / vLLM …",
        connector="local",
        runtime="builtin",
        detect=lambda: True,
    ),
    ConnectionProfile(
        id="acp",
        label="ACP (Agent Client Protocol)",
        description="Connect any installed external ACP-compatible coding agent",
        connector="acp-picker",
        detect=lambda: True,
    ),
    ConnectionProfile(
        id="byok",
        label="BYOK (Bring Your Own Key)",
        description="Use your own API key: OpenAI / Anthropic / Gemini / Z.AI / 100+ providers",
        connector="byok",
        runtime="builtin",
        detect=_byok_ready,
        unavailable_hint="set a provider API key (e.g. OPENAI_API_KEY), or pick one to see setup",
    ),
    ConnectionProfile(
        id="subscriptions",
        label="Subscriptions",
        description=("Use coding-agent plans you already pay for through vendor-managed sign-in"),
        connector="subscription-picker",
        detect=lambda: True,
    ),
    ConnectionProfile(
        id="other-harnesses",
        label="Other harnesses",
        description=("Browse optional non-ACP harness integrations, including Hugging Face Tau"),
        connector="harness-picker",
        detect=lambda: True,
    ),
]

# The subscription submenu keeps the established regional grouping and order.
_SUBSCRIPTION_PROFILES: List[ConnectionProfile] = [
    ConnectionProfile(
        id="codex",
        label="Codex subscription",
        description="Drive OpenAI Codex with your ChatGPT/Codex login (~/.codex)",
        connector="runtime",
        group="US Coding Agents",
        menu=CONNECT_MENU_SUBSCRIPTIONS,
        runtime="codex-sdk",
        self_contained=True,
        detect=_codex_ready,
        unavailable_hint=missing_extra_hint("codex-sdk", suffix="then run `codex login`"),
    ),
    ConnectionProfile(
        id="cursor",
        label="Cursor subscription",
        description=(
            "Use Cursor Agent over ACP through the account already signed in to Cursor CLI"
        ),
        connector="acp",
        group="US Coding Agents",
        menu=CONNECT_MENU_SUBSCRIPTIONS,
        acp_agent="cursor",
        self_contained=True,
        detect=_cursor_cli_ready,
        unavailable_hint=(
            "install with `curl https://cursor.com/install -fsS | bash`, "
            "then run `cursor-agent login`"
        ),
    ),
    ConnectionProfile(
        id="amp",
        label="Amp subscription",
        description="Use Amp through its local account login and ACP adapter",
        connector="acp",
        group="US Coding Agents",
        menu=CONNECT_MENU_SUBSCRIPTIONS,
        acp_agent="amp",
        self_contained=True,
        detect=_amp_cli_ready,
        unavailable_hint=(
            "install Amp and run `amp login`, then install its adapter with "
            "`uv tool install acp-amp`"
        ),
    ),
    ConnectionProfile(
        id="antigravity",
        label="Antigravity CLI",
        description="Use Google's Antigravity agent with your Google Sign-In",
        connector="runtime",
        group="US Coding Agents",
        menu=CONNECT_MENU_SUBSCRIPTIONS,
        runtime="antigravity-cli",
        self_contained=True,
        detect=_antigravity_cli_ready,
        unavailable_hint=(
            "install or update agy from https://antigravity.google/docs/cli-install "
            "(SuperQode requires 1.1.1+)"
        ),
    ),
    ConnectionProfile(
        id="grok",
        label="Grok subscription",
        description=(
            "Grok Build coding agent on your X/SuperGrok login (xAI's own harness, "
            "over ACP). SuperQode harness on the same plan: :grok api"
        ),
        # Subscriptions default to the vendor's own agent. Running SuperQode's
        # harness on this plan is the explicit opt-in `:grok api [model]`
        # (grok-cli provider).
        connector="acp",
        group="US Coding Agents",
        menu=CONNECT_MENU_SUBSCRIPTIONS,
        acp_agent="grok",
        detect=_grok_cli_ready,
        unavailable_hint="install the Grok CLI, then run `grok login` (or `grok login --device-auth`)",
    ),
    ConnectionProfile(
        id="copilot",
        label="GitHub Copilot",
        description=(
            "Use your Copilot plan; prefers the SDK for per-tool approvals and "
            "resumable sessions, otherwise uses the official CLI directly"
        ),
        connector="copilot",
        group="US Coding Agents",
        menu=CONNECT_MENU_SUBSCRIPTIONS,
        runtime="copilot-sdk",
        acp_agent="copilot",
        self_contained=True,
        detect=_copilot_subscription_ready,
        unavailable_hint=(
            f"{missing_extra_hint('copilot-sdk')}; or run "
            "`npm install -g @github/copilot`; then run `copilot login`"
        ),
    ),
    # Gemini CLI is deliberately absent from Subscriptions. It is an
    # enterprise/API-key route rather than a subscription one, and Google has
    # moved consumer plans to Antigravity. Subscriptions must never put a user
    # on metered API billing. The agent is still reachable through the ACP
    # channel with `:connect acp gemini` for anyone who still runs it.
    ConnectionProfile(
        id="devin",
        label="Devin",
        description="Cognition's Devin CLI on your Devin account, through its native ACP server",
        connector="acp",
        group="US Coding Agents",
        menu=CONNECT_MENU_SUBSCRIPTIONS,
        acp_agent="devin",
        self_contained=True,
        detect=_devin_cli_ready,
        unavailable_hint=(
            "run `curl -fsSL https://cli.devin.ai/install.sh | bash`, then run `devin auth login`"
        ),
    ),
    ConnectionProfile(
        id="droid",
        label="Factory Droid subscription",
        description="Use Factory Droid through its locally authenticated CLI and ACP mode",
        connector="acp",
        group="US Coding Agents",
        menu=CONNECT_MENU_SUBSCRIPTIONS,
        acp_agent="droid",
        self_contained=True,
        detect=_droid_cli_ready,
        unavailable_hint="install Factory Droid, then complete the vendor CLI sign-in",
    ),
    ConnectionProfile(
        id="kiro",
        label="Kiro subscription",
        description=("Use a Kiro or Amazon Q Developer plan over ACP through Kiro CLI sign-in"),
        connector="acp",
        group="US Coding Agents",
        menu=CONNECT_MENU_SUBSCRIPTIONS,
        acp_agent="kiro",
        self_contained=True,
        detect=_kiro_cli_ready,
        unavailable_hint=(
            "install Kiro CLI from https://kiro.dev/docs/cli/, then sign in "
            "with your Kiro or Amazon Q Developer account"
        ),
    ),
    ConnectionProfile(
        id="glm-cli",
        label="GLM Coding Plan",
        description="Use a paid GLM Coding Plan through its authenticated ACP agent",
        connector="acp",
        group="China Coding Agents",
        menu=CONNECT_MENU_SUBSCRIPTIONS,
        acp_agent="glm",
        detect=_glm_cli_ready,
        unavailable_hint=(
            "run `npm install -g glm-acp-agent`, then set your Z.AI key for the agent"
        ),
    ),
    ConnectionProfile(
        id="qwen-code",
        label="Qwen Code",
        description=("QwenLM's first-party open-source coding agent through its stable ACP mode"),
        connector="acp",
        group="China Coding Agents",
        menu=CONNECT_MENU_SUBSCRIPTIONS,
        acp_agent="qwen",
        self_contained=True,
        detect=_qwen_code_ready,
        unavailable_hint=("run `npm install -g @qwen-code/qwen-code`, then run `qwen auth`"),
    ),
    ConnectionProfile(
        id="kimi-code",
        label="Kimi Code",
        description=("Moonshot AI's first-party coding agent through its official ACP server"),
        connector="acp",
        group="China Coding Agents",
        menu=CONNECT_MENU_SUBSCRIPTIONS,
        acp_agent="kimi",
        self_contained=True,
        detect=_kimi_code_ready,
        unavailable_hint=(
            "run `curl -fsSL https://code.kimi.com/kimi-code/install.sh | bash`, "
            "then run `kimi` and complete `/login`"
        ),
    ),
]

_PROFILES: List[ConnectionProfile] = [*_ROOT_PROFILES, *_SUBSCRIPTION_PROFILES]

# Compatibility-only profiles remain directly resolvable without appearing in
# the Connect picker or its completion list.
_LEGACY_PROFILES: List[ConnectionProfile] = [
    ConnectionProfile(
        id="copilot-cli",
        label="GitHub Copilot CLI",
        description="Official Copilot CLI over ACP; also available in the ACP picker",
        connector="acp",
        acp_agent="copilot",
        self_contained=True,
        detect=_copilot_acp_ready,
        unavailable_hint="run `npm install -g @github/copilot`, then run `copilot login`",
    ),
    ConnectionProfile(
        id="copilot-acp",
        label="GitHub Copilot ACP",
        description="Older alias for the GitHub Copilot CLI route",
        connector="acp",
        acp_agent="copilot",
        detect=_copilot_acp_ready,
        unavailable_hint="run `npm install -g @github/copilot`, then run `copilot login`",
    ),
    ConnectionProfile(
        id="claude-api",
        label="Claude Agent SDK (API key)",
        description="Compatibility route for the Anthropic API-key runtime; prefer BYOK",
        connector="runtime",
        runtime="claude-agent-sdk",
        self_contained=True,
        detect=lambda: importlib.util.find_spec("claude_agent_sdk") is not None
        and bool(os.environ.get("ANTHROPIC_API_KEY")),
        unavailable_hint=missing_extra_hint(
            "claude-agent-sdk", suffix="then set ANTHROPIC_API_KEY"
        ),
    ),
    ConnectionProfile(
        id="zai",
        label="Z.AI GLM API",
        description="Compatibility route for the Z.AI general API; prefer BYOK",
        connector="byok",
        runtime="builtin",
        byok_provider="zai",
        detect=_zai_ready,
        unavailable_hint="set ZAI_API_KEY",
    ),
]

_BY_ID = {p.id: p for p in (*_PROFILES, *_LEGACY_PROFILES)}

_BY_MENU = {
    CONNECT_MENU_ROOT: _ROOT_PROFILES,
    CONNECT_MENU_SUBSCRIPTIONS: _SUBSCRIPTION_PROFILES,
}


def list_connection_profiles(menu: Optional[str] = None) -> List[ConnectionProfile]:
    """Profiles for one ``:connect`` menu, or every visible profile.

    ``menu=None`` returns the flat list (root first, then subscriptions) used
    for completion and name lookup. Pass a menu id to get exactly what that
    screen shows, in display order.
    """
    if menu is None:
        return list(_PROFILES)
    return list(_BY_MENU.get(menu, ()))


def get_connection_profile(id_or_label: str) -> Optional[ConnectionProfile]:
    """Look up a profile by id (preferred) or, failing that, by label match."""
    key = (id_or_label or "").strip().lower()
    if key in _BY_ID:
        return _BY_ID[key]
    for profile in _PROFILES:
        if profile.label.lower() == key:
            return profile
    return None


def connection_profile_ids(
    *, include_legacy: bool = False, menu: Optional[str] = None
) -> List[str]:
    """Visible profile ids, optionally scoped to a menu or including aliases."""
    profiles = list_connection_profiles(menu)
    if include_legacy and menu is None:
        profiles = [*profiles, *_LEGACY_PROFILES]
    return [p.id for p in profiles]


__all__ = [
    "CONNECT_MENUS",
    "CONNECT_MENU_ROOT",
    "CONNECT_MENU_SUBSCRIPTIONS",
    "ConnectionProfile",
    "list_connection_profiles",
    "get_connection_profile",
    "connection_profile_ids",
]
