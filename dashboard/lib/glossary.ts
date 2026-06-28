// Plain-language explanations for every technical term in the console.
// Used by the <Term> tooltip component so operators never need the strategy spec.

export const GLOSSARY: Record<string, string> = {
  RVOL: "Relative Volume: today's volume vs the 50-day average. 5x means 5× normal activity.",
  MACD: 'Momentum indicator. The bot requires a positive MACD histogram before any entry (gate E4).',
  'Tier A': "The wide net — stocks moving enough to watch, but not yet meeting all of Ross's trade rules.",
  'Tier B': "Meets all 5 of Ross's trade requirements (the Five Pillars). Only Tier B symbols are traded.",
  'Mental Stop':
    'The bot tracks the stop price internally and exits if it breaks — it never places a resting stop order (prevents market-maker stop-hunting). Spec U13.',
  Conviction: 'Score 0–10 based on pattern quality, RVOL, float size, and attention rank.',
  'Icebreaker Size':
    'Reduced position size (about 25% of normal) used when the day P&L is negative — the cushion rule.',
  '3-Strikes Rule': '3 consecutive losing trades ends trading for the day (spec U5).',
  'HOT Market':
    'Strong follow-through on breakouts and multiple 100%+ movers. Larger sizes are allowed.',
  'COLD Market': 'Choppy / weak tape. Smaller sizes, A+ setups only. The cautious default.',
  'REHAB Market': 'Micro size while rebuilding confidence after a big loss.',
  Float: 'Shares available to trade. Ross prefers low float (≤20M, ideally <5M) — they move fast.',
  Spread: 'Gap between bid and ask. $0.03–$0.10 is ideal; too tight or too wide is avoided (gate E7).',
  Catalyst: 'Breaking news driving the move (Pillar 5). Without verified news the bot will not enter.',
  'Give-back':
    'How much of the peak profit has been handed back. 25% warns; 50% halts trading (spec U4).',
  'Daily Loss Limit': 'If the day P&L drops below this, the bot halts trading for the day (spec U4).',
  'Risk:Reward': 'Reward vs risk. The bot needs at least 2:1 before a trade qualifies.',
  AUTO_TRADE:
    'When ON, the bot executes orders automatically. When OFF, signals are shown but not traded.',
  'Pillar P1': 'Price is in the $2–$20 sweet spot.',
  'Pillar P2': 'Float is ≤20M shares (lower is better).',
  'Pillar P3': 'RVOL is ≥5x — real momentum.',
  'Pillar P4': 'Up ≥10% on the day — a real move.',
  'Pillar P5': 'A verified breaking-news catalyst.',
  'Entry E2': 'Pullback: red candles after a surge (a healthy pause before continuation).',
  'Entry E3': 'New high: the current candle breaks above the prior candle.',
  'Entry E4': 'MACD is positive / crossing up. Negative MACD is a hard block.',
  'Entry E5': 'Retrace held within 50% of the surge (preferred under 25%).',
  'Entry E6': 'Level-2 order-book support. Bypassed in the demo (Alpaca has no depth feed).',
  'Entry E7': 'Spread is healthy ($0.03–$0.10).',
}

export function termHint(term: string): string {
  return GLOSSARY[term] ?? term
}
