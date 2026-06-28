'use client'

import { Tooltip } from './Tooltip'

// Maps the backend pillar_flags keys → label + plain-language meaning.
const PILLARS: { key: string; label: string; hint: string }[] = [
  { key: 'P1_price', label: 'P1', hint: 'Price $2–$20 — the sweet spot.' },
  { key: 'P2_float', label: 'P2', hint: 'Float ≤20M shares (lower is better).' },
  { key: 'P3_rvol', label: 'P3', hint: 'RVOL ≥5x — real relative volume.' },
  { key: 'P4_roc', label: 'P4', hint: 'Up ≥10% on the day — a real move.' },
  { key: 'P5_catalyst', label: 'P5', hint: 'Verified breaking-news catalyst.' },
]

/** Five colored dots (P1–P5): green = pass, red = fail, each with a tooltip. */
export function PillarDots({ flags }: { flags: Record<string, boolean> }) {
  return (
    <span className="pillar-dots" aria-label="Five Pillars status">
      {PILLARS.map(({ key, label, hint }) => {
        const pass = flags[key]
        return (
          <Tooltip key={key} label={`${label} — ${hint} ${pass ? '✓ pass' : '✗ fail'}`}>
            <span className={`dot ${pass ? 'dot-pass' : 'dot-fail'}`}>{label}</span>
          </Tooltip>
        )
      })}
    </span>
  )
}
