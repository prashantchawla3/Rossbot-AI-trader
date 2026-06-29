"""Multi-provider strategy analyzer — the dashboard "AI Analysis" assistant.

The operator picks a provider + model in the dashboard (Anthropic, OpenAI,
NVIDIA NIM, or Google Gemini); the actual API call is dispatched by
``adapters.llm_providers``. See that module for the verified 2026-06 model IDs,
endpoints, and required env keys.

Given a symbol's live market data, the chosen model scores it against EVERY
Ross-Cameron entry gate (Five Pillars §1, entry gates E2–E7 §2) and returns a
structured JSON verdict the dashboard renders as a card (would_ross_trade,
pillars, entry_gates, suggested_trade).

Returns a deterministic ``_fallback_verdict`` (no API call) when the chosen
provider has no key/SDK or the API errors, so the dashboard degrades gracefully
instead of erroring. ``chat_fn`` is injectable for offline tests.

This is an ADVISORY surface only. A suggested trade is NOT executed here — execution
goes through the Risk Manager gate (DemoEngine.manual_trade). spec §2 / §13.1.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from adapters import llm_providers

# spec §2/§3 — the exact indicators and gates Ross uses; Claude is told to reason
# strictly within these rules and to bias toward SKIP on ambiguity (false-negative = safe).
ANALYZER_SYSTEM_PROMPT = """\
You are RossBot's strategy analysis engine, trained on Ross Cameron's (DaytradeWarrior) \
exact trading rules. You evaluate a single US-equity symbol for an intraday momentum \
day-trade and decide whether Ross would take it.

Apply EVERY gate using the supplied numbers — never invent data. Be direct and specific, \
cite the exact values. Bias toward SKIP when data is missing or ambiguous (a false \
"skip" is safe; a false "trade" loses money).

Rules you enforce:
- Five Pillars (must all pass for Tier B / tradeable): P1 price $2-$20, P2 float <=20M \
(optimal <5M), P3 RVOL >=5x, P4 change >=10%, P5 catalyst (breaking news).
- Entry gates (AND-gate): E2 pullback (red candles after a surge), E3 new high vs prior \
candle, E4 MACD positive/crossing up (HARD BLOCK if MACD negative), E5 retrace held within \
50% of the surge (preferred <25%), E6 Level-2 support (often UNAVAILABLE -> null/bypassed), \
E7 spread healthy ($0.03-$0.10 ideal).
- 2:1 minimum reward:risk before a trade qualifies.
- Never short a stock making new highs; never bottom-fish; limit orders only.

Use pass=null when the data cannot confirm or deny a gate (e.g. catalyst or L2).

Return ONLY a valid JSON object (no prose, no markdown fences) with this exact structure:
{
  "symbol": "STR",
  "would_ross_trade": true,
  "confidence": 7,
  "verdict_summary": "one or two sentences",
  "pillars": {
    "P1_price":   {"pass": true,  "value": "$4.25", "rule": "$2-$20",        "note": "..."},
    "P2_float":   {"pass": true,  "value": "2.5M",  "rule": "<=20M",         "note": "..."},
    "P3_rvol":    {"pass": true,  "value": "12.3x", "rule": ">=5x",          "note": "..."},
    "P4_change":  {"pass": true,  "value": "+45.2%","rule": ">=10%",         "note": "..."},
    "P5_catalyst":{"pass": null,  "value": "Unknown","rule": "Breaking news","note": "..."}
  },
  "entry_gates": {
    "E2_pullback":{"pass": true, "note": "..."},
    "E3_new_high":{"pass": true, "note": "..."},
    "E4_macd":    {"pass": true, "note": "..."},
    "E5_retrace": {"pass": true, "note": "..."},
    "E6_l2":      {"pass": null, "note": "L2 bypassed - no depth data."},
    "E7_spread":  {"pass": true, "note": "..."}
  },
  "suggested_trade": {
    "action": "BUY",
    "entry_price": 4.30, "stop_price": 4.10, "risk_per_share": 0.20,
    "suggested_shares": 500, "target_1": 4.60, "target_2": 5.00,
    "risk_reward": 2.5, "pattern": "Micro-Pullback", "conviction": "HIGH"
  },
  "warnings": ["..."],
  "ross_would_say": "a short in-character quote"
}
"""


class StrategyAnalyzer:
    """Zero-shot single-symbol analyzer over a selectable provider/model (spec §2).

    The provider + model are chosen per-request (dashboard picker); the constructor
    only sets the defaults used when the request leaves them blank. ``chat_fn`` is
    injectable for offline tests — it must mirror ``llm_providers.chat``'s signature
    and return ``(text, provider_key, model_id)``.
    """

    def __init__(
        self,
        default_provider: str | None = None,
        default_model: str | None = None,
        chat_fn: Callable[..., tuple[str, str, str]] | None = None,
    ) -> None:
        self._default_provider = default_provider or llm_providers.DEFAULT_PROVIDER
        self._default_model = default_model
        self._chat = chat_fn or llm_providers.chat

    def analyze(
        self,
        symbol: str,
        market_data: dict[str, Any],
        provider: str | None = None,
        model: str | None = None,
    ) -> dict[str, Any]:
        """Return a structured verdict dict for ``symbol`` given its live market data.

        ``market_data`` keys (best-effort, any may be None): price, change_pct, rvol,
        float_shares, macd_hist, macd_positive, spread, bid, ask, bars (list of recent
        OHLC dicts oldest→newest). Falls back to a deterministic verdict on any error.
        """
        sym = symbol.upper().strip()
        prov = provider or self._default_provider
        user_msg = self._build_prompt(sym, market_data)

        try:
            raw_text, used_provider, used_model = self._chat(
                prov,
                model or self._default_model,
                ANALYZER_SYSTEM_PROMPT,
                user_msg,
                max_tokens=1200,
            )
        except llm_providers.LLMError as exc:
            return self._fallback_verdict(sym, market_data, str(exc))
        except Exception as exc:  # noqa: BLE001 — never let the analyzer hard-fail
            return self._fallback_verdict(sym, market_data, f"api_error: {exc}")

        raw_text = (raw_text or "").strip()
        # Strip accidental markdown fences (same defensive parse as the catalyst classifier).
        if raw_text.startswith("```"):
            parts = raw_text.split("```")
            raw_text = parts[1] if len(parts) > 1 else parts[0]
            if raw_text.startswith("json"):
                raw_text = raw_text[4:]
        # Some models (e.g. reasoning models) wrap JSON in prose — grab the JSON object.
        if not raw_text.lstrip().startswith("{"):
            start, end = raw_text.find("{"), raw_text.rfind("}")
            if start != -1 and end != -1 and end > start:
                raw_text = raw_text[start : end + 1]
        try:
            obj = json.loads(raw_text)
        except Exception:  # noqa: BLE001
            return self._fallback_verdict(sym, market_data, "unparseable_response")
        obj["source"] = used_provider
        obj["provider"] = used_provider
        obj["model"] = used_model
        obj.setdefault("symbol", sym)
        return obj

    # ── helpers ──────────────────────────────────────────────────────────────────

    @staticmethod
    def _build_prompt(symbol: str, md: dict[str, Any]) -> str:
        bars = md.get("bars") or []
        bar_lines = "\n".join(
            f"  {b.get('time', '')}: O={b.get('open')} H={b.get('high')} "
            f"L={b.get('low')} C={b.get('close')} V={b.get('volume')}"
            for b in bars[-12:]
        )
        flt = md.get("float_shares")
        flt_str = f"{flt / 1_000_000:.1f}M" if isinstance(flt, (int, float)) else "Unknown"
        return f"""\
Analyze {symbol} for a Ross-Cameron intraday momentum trade.

Snapshot:
  price:       {md.get('price')}
  change_pct:  {md.get('change_pct')}%
  rvol:        {md.get('rvol')}
  float:       {flt_str}
  bid / ask:   {md.get('bid')} / {md.get('ask')}
  spread:      {md.get('spread')}
  MACD hist:   {md.get('macd_hist')} (positive={md.get('macd_positive')})
  catalyst:    {md.get('catalyst', 'unknown — no licensed news feed')}

Recent 1-min bars (oldest→newest):
{bar_lines or '  (no bar data available)'}

Score every Pillar and entry gate, then produce the JSON verdict.
"""

    @staticmethod
    def _fallback_verdict(symbol: str, md: dict[str, Any], reason: str) -> dict[str, Any]:
        """Deterministic rule-of-thumb verdict when the chosen AI model is unavailable.

        Computed directly from the numbers so the dashboard still shows a usable card.
        """
        price = _num(md.get("price"))
        change = _num(md.get("change_pct"))
        rvol = _num(md.get("rvol"))
        flt = md.get("float_shares")
        spread = _num(md.get("spread"))
        macd_pos = md.get("macd_positive")

        p1 = price is not None and 2 <= price <= 20
        p2 = isinstance(flt, (int, float)) and flt <= 20_000_000
        p3 = rvol is not None and rvol >= 5
        p4 = change is not None and change >= 10
        e4 = bool(macd_pos)
        e7 = spread is not None and 0.03 <= spread <= 0.10
        would = bool(p1 and p2 and p3 and p4 and e4)

        def cell(passed: bool | None, value: str, rule: str, note: str) -> dict[str, Any]:
            return {"pass": passed, "value": value, "rule": rule, "note": note}

        return {
            "symbol": symbol,
            "would_ross_trade": would,
            "confidence": 5 if would else 2,
            "verdict_summary": (
                f"Heuristic verdict (AI model unavailable: {reason}). "
                + ("Pillars/MACD align — viable." if would else "One or more hard gates fail.")
            ),
            "pillars": {
                "P1_price": cell(p1, f"${price}" if price is not None else "?", "$2-$20", "sweet spot"),
                "P2_float": cell(p2, _fmt_float(flt), "<=20M", "lower is better"),
                "P3_rvol": cell(p3, f"{rvol}x" if rvol is not None else "?", ">=5x", "momentum"),
                "P4_change": cell(p4, f"{change}%" if change is not None else "?", ">=10%", "move size"),
                "P5_catalyst": cell(None, "Unknown", "Breaking news", "no news feed in demo"),
            },
            "entry_gates": {
                "E2_pullback": {"pass": None, "note": "needs bar pattern review"},
                "E3_new_high": {"pass": None, "note": "needs bar pattern review"},
                "E4_macd": {"pass": e4, "note": "MACD positive" if e4 else "MACD not positive — HARD BLOCK"},
                "E5_retrace": {"pass": None, "note": "needs surge/retrace review"},
                "E6_l2": {"pass": None, "note": "L2 bypassed — no depth data"},
                "E7_spread": {"pass": e7, "note": "ideal $0.03-$0.10"},
            },
            "suggested_trade": None,
            "warnings": [f"AI analysis unavailable ({reason}); heuristic only.",
                         "Catalyst (P5) unverified — check news manually."],
            "ross_would_say": (
                "Clean low-float momentum with positive MACD — if there's news, this is a setup."
                if would else "No news, no MACD, no trade. Wait for the A+ setup."
            ),
            "source": "fallback",
        }


def _num(v: Any) -> float | None:
    try:
        return float(str(v))
    except (TypeError, ValueError):
        return None


def _fmt_float(flt: Any) -> str:
    if isinstance(flt, (int, float)):
        return f"{flt / 1_000_000:.1f}M"
    return "Unknown"


__all__ = ["StrategyAnalyzer", "ANALYZER_SYSTEM_PROMPT"]
