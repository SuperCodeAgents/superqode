"""Connection profiles — the product/account-level choices in ``:connect``.

A *connection source* is what the user is connecting SuperQode to (Codex
subscription, Claude, a BYOK provider, a local model, an ACP agent). Each
profile declares a ``connector`` that the TUI/CLI dispatches on:

    runtime      self-contained runtime (own model+auth), e.g. codex-sdk
    acp          a specific ACP agent by short_name, e.g. "claude" or "grok"
    byok         the BYOK provider/model picker, optionally pinned to one provider
    local        the local provider/model picker
    acp-picker   the generic "pick any ACP agent" list
    harness-picker optional non-ACP harness integrations
    subscription-picker the vendor-subscription submenu (Codex, Grok, Copilot, …)
    external-cli a local vendor TUI that does not expose ACP/headless events yet

Profiles are grouped into **menus** so the first screen a new user sees stays
short. ``root`` holds the five ways to connect (local, ACP, BYOK, subscriptions,
other harnesses); ``subscriptions`` holds the vendor coding agents you sign in
to. Every profile stays directly reachable by id (``:connect codex``) regardless
of which menu shows it.

This module has no TUI dependencies so it can be unit-tested and reused by both
the TUI and the CLI. New products (Claude Agent SDK, Antigravity) slot in as new
profiles without touching the connect flow.
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
    connector: str  # runtime | acp | byok | local | acp-picker | harness-picker | external-cli
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


def _claude_agent_ready() -> bool:
    """Claude Agent SDK installed + an Anthropic API key set (API-key runtime)."""
    if importlib.util.find_spec("claude_agent_sdk") is None:
        return False
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


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


def _gemini_cli_ready() -> bool:
    """Google's Gemini CLI is installed and can serve its ACP mode."""
    return shutil.which("gemini") is not None


def _glm_cli_ready() -> bool:
    """The GLM ACP agent CLI is on PATH."""
    return shutil.which("glm-acp-agent") is not None


def _devin_cli_ready() -> bool:
    """Cognition's Devin CLI is installed (it owns its own sign-in)."""
    return shutil.which("devin") is not None


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
# harnesses. Everything a vendor signs you in to lives one keypress deeper so
# the first connect screen stays readable.
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
        description="Connect any external ACP-compatible coding agent (incl. local Claude Code)",
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
        description=("Vendor agents you sign in to: Codex, Claude, Grok, Copilot, Gemini, Devin …"),
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
        id="claude",
        label="Claude Agent SDK",
        description="Use your Anthropic API key via claude-agent-sdk "
        "(local Claude Code over ACP is available under 'ACP agent')",
        connector="runtime",
        group="US Coding Agents",
        menu=CONNECT_MENU_SUBSCRIPTIONS,
        runtime="claude-agent-sdk",
        self_contained=True,
        detect=_claude_agent_ready,
        unavailable_hint=missing_extra_hint(
            "claude-agent-sdk", suffix="then set ANTHROPIC_API_KEY"
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
            "via the official CLI). SuperQode harness on the same plan: :grok api"
        ),
        # Subscriptions default to the vendor's own agent, matching the Codex
        # and Claude profiles. Running SuperQode's harness on this plan is the
        # explicit opt-in `:grok api [model]` (grok-cli provider).
        connector="acp",
        group="US Coding Agents",
        menu=CONNECT_MENU_SUBSCRIPTIONS,
        acp_agent="grok",
        detect=_grok_cli_ready,
        unavailable_hint="install the Grok CLI, then run `grok login` (or `grok login --device-auth`)",
    ),
    ConnectionProfile(
        id="copilot",
        label="GitHub Copilot SDK",
        description=(
            "Embed GitHub Copilot with your Copilot licence; SuperQode adds "
            "HarnessSpec context, policy, evidence, evaluation, and session controls"
        ),
        connector="runtime",
        group="US Coding Agents",
        menu=CONNECT_MENU_SUBSCRIPTIONS,
        runtime="copilot-sdk",
        self_contained=True,
        detect=_copilot_sdk_ready,
        unavailable_hint=missing_extra_hint(
            "copilot-sdk",
            suffix="then run `copilot login` or set COPILOT_GITHUB_TOKEN",
        ),
    ),
    ConnectionProfile(
        id="gemini-cli",
        label="Gemini CLI",
        description=(
            "Google's Gemini CLI over ACP (enterprise/API-key route; consumer "
            "Google AI plans now use Antigravity)"
        ),
        connector="acp",
        group="US Coding Agents",
        menu=CONNECT_MENU_SUBSCRIPTIONS,
        acp_agent="gemini",
        self_contained=True,
        detect=_gemini_cli_ready,
        unavailable_hint=(
            "run `npm install -g @google/gemini-cli`, then sign in or set GEMINI_API_KEY"
        ),
    ),
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
        id="glm-cli",
        label="GLM CLI",
        description="Run GLM models through the community GLM ACP agent CLI",
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
        id="zai",
        label="Z.AI GLM API",
        description="GLM-5.2/5.x with the SuperQode harness via Z.AI's general API",
        connector="byok",
        group="China Coding Agents",
        menu=CONNECT_MENU_SUBSCRIPTIONS,
        runtime="builtin",
        byok_provider="zai",
        detect=_zai_ready,
        unavailable_hint=("set ZAI_API_KEY (general API key, not a restricted Coding Plan key)"),
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
# the root Connect picker or its completion list.
_LEGACY_PROFILES: List[ConnectionProfile] = [
    ConnectionProfile(
        id="copilot-acp",
        label="GitHub Copilot ACP",
        description="Legacy shortcut for the Copilot CLI agent in the ACP catalog",
        connector="acp",
        acp_agent="copilot",
        detect=_copilot_acp_ready,
        unavailable_hint="install @github/copilot, then run `copilot login`",
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
