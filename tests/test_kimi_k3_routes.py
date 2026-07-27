"""Kimi K3 routing across the hosts that serve its open weights.

Each host spells the same weights differently, so the ids are pinned here: a
wrong id in a picker sends the user to a dead end rather than a model.
"""

from __future__ import annotations

import pytest

from superqode.local.packs import detect_pack
from superqode.providers.registry import PROVIDERS, ProviderCategory


#: Verified against each host's own model page on 2026-07-27.
EXPECTED_MODEL_IDS = {
    "moonshot": "kimi-k3",
    "baseten": "moonshot-ai/Kimi-K3",
    "fireworks": "accounts/fireworks/models/kimi-k3",
    "together": "moonshotai/Kimi-K3",
    "openrouter": "moonshotai/kimi-k3",
    "siliconflow": "moonshotai/Kimi-K3",
    # Self-hosting serves the published weights repository directly.
    "vllm": "moonshotai/Kimi-K3-MXFP4",
    "sglang": "moonshotai/Kimi-K3-MXFP4",
}


@pytest.mark.parametrize("provider_id,model_id", sorted(EXPECTED_MODEL_IDS.items()))
def test_provider_offers_kimi_k3(provider_id, model_id):
    provider = PROVIDERS.get(provider_id)

    assert provider is not None, f"{provider_id} is not registered"
    assert model_id in provider.example_models, (
        f"{provider_id} should offer {model_id!r}; has {provider.example_models}"
    )


def test_baseten_is_registered_as_an_openai_compatible_host():
    provider = PROVIDERS["baseten"]

    assert provider.category is ProviderCategory.MODEL_HOSTS
    assert provider.default_base_url == "https://inference.baseten.co/v1"
    assert "BASETEN_API_KEY" in provider.env_vars
    assert provider.dynamic is True


def test_modal_requires_a_user_supplied_endpoint():
    """Modal deploys to your own URL rather than a shared inference API.

    Shipping a default base URL would imply a shared endpoint that does not
    exist, so the user must point at the deployment they created.
    """
    provider = PROVIDERS["modal"]

    assert provider.base_url_env == "MODAL_BASE_URL"
    assert provider.default_base_url is None


@pytest.mark.parametrize(
    "model_text",
    [
        "kimi-k3",
        "moonshotai/Kimi-K3",
        "moonshot-ai/Kimi-K3",
        "accounts/fireworks/models/kimi-k3",
        "openrouter/moonshotai/kimi-k3",
        "moonshotai/Kimi-K3-MXFP4",
    ],
)
def test_every_k3_spelling_resolves_to_the_kimi_pack(model_text):
    """The reasoning/tool policy must survive whichever host serves K3."""
    pack = detect_pack(model_text)

    assert pack is not None
    assert pack.name == "kimi"


def test_hosts_without_confirmed_k3_do_not_advertise_it():
    """Only hosts checked against their own model page may list K3."""
    for provider_id, provider in PROVIDERS.items():
        if provider_id in EXPECTED_MODEL_IDS:
            continue
        offending = [m for m in provider.example_models if "k3" in m.lower()]
        assert not offending, f"{provider_id} advertises unverified K3 ids: {offending}"
