"""Multi-provider LLM gateway for the dashboard "AI Analysis" assistant.

The operator can grade a symbol with a model from ANY of four providers. Three of
them (OpenAI, NVIDIA NIM, Google Gemini) expose an **OpenAI-compatible**
``/v1/chat/completions`` endpoint, so they share one code path via the ``openai``
SDK with a per-provider ``base_url``. Anthropic uses its own SDK.

This is an ADVISORY surface only (spec §2 / §13.1). The model never executes a
trade — a suggested trade is routed through the Risk Manager gate
(``DemoEngine.manual_trade``), which can VETO or RESIZE it.

Web-verified 2026-06 (model IDs + endpoints):
- Anthropic — native ``anthropic`` SDK. Models: claude-opus-4-8 / 4-7,
  claude-sonnet-4-6, claude-haiku-4-5. Key: ANTHROPIC_API_KEY.
  (claude-api skill, 2026-06.)
- OpenAI — https://api.openai.com/v1 . Models: gpt-5.5, gpt-5, gpt-5-mini,
  gpt-5-nano, gpt-4.1-mini, gpt-4o-mini, gpt-oss-120b. Key: OPENAI_API_KEY.
  (developers.openai.com/api/docs/models, 2026-06.)
- NVIDIA NIM — https://integrate.api.nvidia.com/v1 (free tier, OpenAI-compatible,
  100+ models). Flagship 2026 models: minimaxai/minimax-m3,
  nvidia/nemotron-3-ultra-550b-a55b, moonshotai/kimi-k2.6,
  mistralai/mistral-medium-3.5-128b, deepseek-ai/deepseek-v4-pro, z-ai/glm-5.1.
  Key: NVIDIA_API_KEY (nvapi-...). (build.nvidia.com/models, 2026-06.)
- Google Gemini — https://generativelanguage.googleapis.com/v1beta/openai/
  (OpenAI-compatible). Models: gemini-3.5-flash, gemini-3.1-flash-lite,
  gemini-2.5-pro, gemini-2.5-flash, gemini-2.5-flash-lite.
  Key: GEMINI_API_KEY (or GOOGLE_API_KEY). (ai.google.dev/gemini-api/docs/openai.)

Every provider degrades gracefully: a missing key/SDK or an API error raises
``LLMError``, which the caller (``StrategyAnalyzer``) turns into a deterministic
heuristic verdict so the dashboard never hard-errors.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


class LLMError(RuntimeError):
    """Raised when a provider call cannot be completed (no key, no SDK, API error)."""


@dataclass(frozen=True)
class ModelInfo:
    id: str
    label: str


@dataclass(frozen=True)
class Provider:
    key: str
    label: str
    # The first env var is canonical; extras are accepted as aliases (e.g. GOOGLE_API_KEY).
    env_keys: tuple[str, ...]
    kind: str  # "anthropic" | "openai"
    default_model: str
    models: list[ModelInfo] = field(default_factory=list)
    base_url: str | None = None  # None for the native Anthropic SDK
    note: str = ""

    @property
    def env_key(self) -> str:
        return self.env_keys[0]


# ── provider registry ─────────────────────────────────────────────────────────
# Ordering = the order shown in the dashboard selector. Anthropic stays first
# (the existing default), NVIDIA is highlighted as the free option.

PROVIDERS: dict[str, Provider] = {
    "anthropic": Provider(
        key="anthropic",
        label="Anthropic (Claude)",
        env_keys=("ANTHROPIC_API_KEY",),
        kind="anthropic",
        default_model="claude-sonnet-4-6",
        models=[
            ModelInfo("claude-opus-4-8", "Claude Opus 4.8 (most capable)"),
            ModelInfo("claude-opus-4-7", "Claude Opus 4.7"),
            ModelInfo("claude-sonnet-4-6", "Claude Sonnet 4.6 (balanced — default)"),
            ModelInfo("claude-haiku-4-5", "Claude Haiku 4.5 (fast/cheap)"),
        ],
        note="Existing default. Best instruction-following for the Ross rule set.",
    ),
    "nvidia": Provider(
        key="nvidia",
        label="NVIDIA NIM (free)",
        env_keys=("NVIDIA_API_KEY",),
        kind="openai",
        base_url="https://integrate.api.nvidia.com/v1",
        default_model="deepseek-ai/deepseek-v4-pro",
        models=[
            ModelInfo("deepseek-ai/deepseek-v4-pro", "DeepSeek V4 Pro (flagship reasoning)"),
            ModelInfo("z-ai/glm-5.1", "GLM-5.1 (Z.ai — agentic/coding)"),
            ModelInfo("moonshotai/kimi-k2.6", "Kimi K2.6 (Moonshot — 1T MoE, long context)"),
            ModelInfo("nvidia/nemotron-3-ultra-550b-a55b", "Nemotron 3 Ultra 550B (NVIDIA)"),
            ModelInfo("minimaxai/minimax-m3", "MiniMax M3 (multimodal MoE, tool-calling)"),
            ModelInfo("mistralai/mistral-medium-3.5-128b", "Mistral Medium 3.5 128B"),
        ],
        note="Free developer tier — get an 'nvapi-' key at build.nvidia.com. 100+ models; "
        "you can also type any model slug from build.nvidia.com/models.",
    ),
    "openai": Provider(
        key="openai",
        label="OpenAI (GPT)",
        env_keys=("OPENAI_API_KEY",),
        kind="openai",
        base_url="https://api.openai.com/v1",
        default_model="gpt-5-mini",
        models=[
            ModelInfo("gpt-5.5", "GPT-5.5 (flagship)"),
            ModelInfo("gpt-5", "GPT-5"),
            ModelInfo("gpt-5-mini", "GPT-5 mini (fast)"),
            ModelInfo("gpt-5-nano", "GPT-5 nano (cheapest)"),
            ModelInfo("gpt-4.1-mini", "GPT-4.1 mini"),
            ModelInfo("gpt-4o-mini", "GPT-4o mini"),
        ],
        note="Get a key at platform.openai.com.",
    ),
    "google": Provider(
        key="google",
        label="Google (Gemini)",
        env_keys=("GEMINI_API_KEY", "GOOGLE_API_KEY"),
        kind="openai",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        default_model="gemini-2.5-flash",
        models=[
            ModelInfo("gemini-3.5-flash", "Gemini 3.5 Flash (latest)"),
            ModelInfo("gemini-3.1-flash-lite", "Gemini 3.1 Flash-Lite"),
            ModelInfo("gemini-2.5-pro", "Gemini 2.5 Pro"),
            ModelInfo("gemini-2.5-flash", "Gemini 2.5 Flash (fast)"),
            ModelInfo("gemini-2.5-flash-lite", "Gemini 2.5 Flash-Lite (cheapest)"),
        ],
        note="Get a key at aistudio.google.com. Uses the OpenAI-compatible endpoint.",
    ),
}

DEFAULT_PROVIDER = "anthropic"


def get_api_key(provider_key: str) -> str | None:
    """First non-empty value among the provider's accepted env vars."""
    prov = PROVIDERS.get(provider_key)
    if prov is None:
        return None
    for env in prov.env_keys:
        val = os.environ.get(env, "").strip()
        if val:
            return val
    return None


def is_configured(provider_key: str) -> bool:
    return get_api_key(provider_key) is not None


def catalog() -> dict[str, object]:
    """Provider/model catalog for the dashboard model picker (GET /api/models)."""
    providers = []
    for prov in PROVIDERS.values():
        providers.append(
            {
                "key": prov.key,
                "label": prov.label,
                "configured": is_configured(prov.key),
                "env_key": prov.env_key,
                "default_model": prov.default_model,
                "note": prov.note,
                "models": [{"id": m.id, "label": m.label} for m in prov.models],
            }
        )
    # Prefer a configured provider as the UI default so the picker opens on something usable.
    default_provider = DEFAULT_PROVIDER
    if not is_configured(default_provider):
        default_provider = next(
            (p.key for p in PROVIDERS.values() if is_configured(p.key)), DEFAULT_PROVIDER
        )
    return {
        "providers": providers,
        "default_provider": default_provider,
        "default_model": PROVIDERS[default_provider].default_model,
    }


def resolve(provider_key: str | None, model: str | None) -> tuple[Provider, str]:
    """Validate a (provider, model) request, falling back to sane defaults.

    An unknown provider falls back to the default; an empty model falls back to the
    provider's default model. A custom model id the operator typed is accepted as-is
    (the catalog is curated, not exhaustive — NVIDIA alone hosts 100+).
    """
    prov = PROVIDERS.get((provider_key or "").strip().lower()) or PROVIDERS[DEFAULT_PROVIDER]
    model_id = (model or "").strip() or prov.default_model
    return prov, model_id


def chat(
    provider_key: str | None,
    model: str | None,
    system: str,
    user: str,
    *,
    max_tokens: int = 1200,
    temperature: float = 0.2,
) -> tuple[str, str, str]:
    """Run a single completion. Returns ``(text, provider_key, model_id)``.

    Raises ``LLMError`` on any failure so the caller can fall back to a heuristic.
    """
    prov, model_id = resolve(provider_key, model)
    api_key = get_api_key(prov.key)
    if not api_key:
        raise LLMError(f"{prov.label}: no API key set (export {prov.env_key}).")

    if prov.kind == "anthropic":
        text = _anthropic_chat(api_key, model_id, system, user, max_tokens)
    else:
        text = _openai_compatible_chat(
            prov.base_url, api_key, model_id, system, user, max_tokens, temperature
        )
    return text, prov.key, model_id


# ── provider back-ends ────────────────────────────────────────────────────────


def _anthropic_chat(api_key: str, model: str, system: str, user: str, max_tokens: int) -> str:
    try:
        import anthropic  # optional dependency (rossbot[vendors])
    except ImportError as exc:  # pragma: no cover - import guard
        raise LLMError("anthropic SDK not installed (pip install anthropic).") from exc
    try:
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return (resp.content[0].text or "").strip()
    except Exception as exc:  # noqa: BLE001 - normalise to LLMError
        raise LLMError(f"Anthropic API error: {exc}") from exc


def _openai_compatible_chat(
    base_url: str | None,
    api_key: str,
    model: str,
    system: str,
    user: str,
    max_tokens: int,
    temperature: float,
) -> str:
    """OpenAI / NVIDIA NIM / Gemini share the OpenAI ``chat.completions`` shape.

    Newer reasoning models (GPT-5 family, o-series) reject ``max_tokens`` and a
    non-default ``temperature`` — they want ``max_completion_tokens`` and no
    sampling override. We try the classic params first, then degrade.
    """
    try:
        from openai import OpenAI  # optional dependency
    except ImportError as exc:  # pragma: no cover - import guard
        raise LLMError("openai SDK not installed (pip install openai).") from exc

    client = OpenAI(api_key=api_key, base_url=base_url)
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    attempts: list[dict[str, object]] = [
        {"max_tokens": max_tokens, "temperature": temperature},
        {"max_completion_tokens": max_tokens},  # GPT-5 / o-series style
        {},  # bare minimum — let the model use its defaults
    ]
    last_exc: Exception | None = None
    for extra in attempts:
        try:
            resp = client.chat.completions.create(model=model, messages=messages, **extra)
            return (resp.choices[0].message.content or "").strip()
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            msg = str(exc).lower()
            # Only retry on parameter-shape complaints; surface real errors immediately.
            retryable = any(
                token in msg
                for token in (
                    "max_tokens",
                    "max_completion_tokens",
                    "temperature",
                    "unsupported",
                    "not supported",
                    "unknown parameter",
                )
            )
            if not retryable:
                break
    raise LLMError(f"OpenAI-compatible API error: {last_exc}")


__all__ = [
    "PROVIDERS",
    "DEFAULT_PROVIDER",
    "Provider",
    "ModelInfo",
    "LLMError",
    "catalog",
    "resolve",
    "chat",
    "get_api_key",
    "is_configured",
]
