"""Claude Sonnet 4.6 strategy analyzer — the dashboard "AI Analysis" assistant.

Model: claude-sonnet-4-6 (verified via the claude-api skill, 2026-06).
Pricing (claude-api skill cache 2026-06): Input $3.00 / MTok | Output $15.00 / MTok.

Given a symbol's live market data, Claude scores it against EVERY Ross-Cameron entry
gate (Five Pillars §1, entry gates E2–E7 §2) and returns a structured JSON verdict that
the dashboard renders as a card (would_ross_trade, pillars, entry_gates, suggested_trade).

Requires ANTHROPIC_API_KEY. Returns a deterministic ``_fallback_verdict`` (no API call)
when the key/SDK is missing so the dashboard degrades gracefully instead of erroring.
``client`` is injectable for offline tests.

This is an ADVISORY surface only. A suggested trade is NOT executed here — execution
goes through the Risk Manager gate (DemoEngine.manual_trade). spec §2 / §13.1.
"""

from __future__ import annotations

import json
import os
from typing import Any

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
    """Zero-shot Claude Sonnet 4.6 analyzer for a single symbol (spec §2)."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "claude-sonnet-4-6",
        client: object | None = None,
    ) -> None:
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self._model = model
        self._client = client  # injected for tests; None → lazy-init on first call

    def _get_client(self) -> object | None:
        if not self._api_key:
            return None
        if self._client is None:
            try:
                import anthropic  # optional dependency (rossbot[vendors])

                self._client = anthropic.Anthropic(api_key=self._api_key)
            except ImportError:
                return None
        return self._client

    def analyze(self, symbol: str, market_data: dict[str, Any]) -> dict[str, Any]:
        """Return a structured verdict dict for ``symbol`` given its live market data.

        ``market_data`` keys (best-effort, any may be None): price, change_pct, rvol,
        float_shares, macd_hist, macd_positive, spread, bid, ask, bars (list of recent
        OHLC dicts oldest→newest). Falls back to a deterministic verdict on any error.
        """
        sym = symbol.upper().strip()
        client = self._get_client()
        if client is None:
            return self._fallback_verdict(sym, market_data, "no_api_key")

        user_msg = self._build_prompt(sym, market_data)
        try:
            response = client.messages.create(  # type: ignore[attr-defined]
                model=self._model,
                max_tokens=1200,
                system=ANALYZER_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_msg}],
            )
            raw_text: str = response.content[0].text.strip()
        except Exception as exc:  # noqa: BLE001
            return self._fallback_verdict(sym, market_data, f"api_error: {exc}")

        # Strip accidental markdown fences (same defensive parse as the catalyst classifier).
        if raw_text.startswith("```"):
            parts = raw_text.split("```")
            raw_text = parts[1] if len(parts) > 1 else parts[0]
            if raw_text.startswith("json"):
                raw_text = raw_text[4:]
        try:
            obj = json.loads(raw_text)
        except Exception:  # noqa: BLE001
            return self._fallback_verdict(sym, market_data, "unparseable_response")
        obj["source"] = "claude"
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
        """Deterministic rule-of-thumb verdict when Claude is unavailable.

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
                f"Heuristic verdict (Claude unavailable: {reason}). "
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
            "warnings": [f"Claude analysis unavailable ({reason}); heuristic only.",
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
