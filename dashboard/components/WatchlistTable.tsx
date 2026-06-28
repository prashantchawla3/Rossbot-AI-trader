'use client'

import { Badge } from './Badge'
import { InfoHint, Tooltip } from './Tooltip'
import type { WatchlistEntry } from '@/lib/types'

interface WatchlistTableProps {
  entries: WatchlistEntry[]
  tier: 'A' | 'B'
}

export function WatchlistTable({ entries, tier }: WatchlistTableProps) {
  if (entries.length === 0) {
    return <p className="empty-state">No Tier {tier} symbols yet</p>
  }

  return (
    <div className="table-wrap">
    <table className="table">
      <thead>
        <tr>
          <th>Symbol</th>
          <th>Price</th>
          <th>
            <span className="eyebrow" style={{ gap: '4px' }}>
              RVOL
              <InfoHint label="Relative volume — how much more this stock is trading today vs. a normal day. 5x means five times the usual." />
            </span>
          </th>
          <th>
            <span className="eyebrow" style={{ gap: '4px' }}>
              Float
              <InfoHint label="Number of shares available to trade. A small float (≤20M) can move fast on heavy buying." />
            </span>
          </th>
          <th>Catalyst</th>
          <th>
            <span className="eyebrow" style={{ gap: '4px' }}>
              Pillars
              <InfoHint label="How many of the 5 quality checks this stock passes (price, float, volume, momentum, news). 5/5 means it qualifies to trade." />
            </span>
          </th>
        </tr>
      </thead>
      <tbody>
        {entries.map((e) => {
          const pillarsPass = Object.values(e.pillar_flags).filter(Boolean).length
          const pillarsTotal = Object.values(e.pillar_flags).length
          const allPass = pillarsPass === pillarsTotal

          return (
            <tr key={e.symbol}>
              <td>
                <strong>{e.symbol}</strong>
              </td>
              <td className="mono">${e.price}</td>
              <td className="mono">{e.rvol}x</td>
              <td className="mono">
                {e.float_shares != null
                  ? `${(e.float_shares / 1_000_000).toFixed(1)}M`
                  : '—'}
              </td>
              <td>
                {e.catalyst ? (
                  <span className="small">{e.catalyst}</span>
                ) : (
                  <span className="small muted">—</span>
                )}
              </td>
              <td>
                <Tooltip
                  label={
                    Object.entries(e.pillar_flags)
                      .map(([k, v]) => `${v ? '✓' : '✗'} ${k}`)
                      .join('   ') || 'No pillar data'
                  }
                >
                  <Badge variant={allPass ? 'success' : 'warn'}>
                    {pillarsPass}/{pillarsTotal}
                  </Badge>
                </Tooltip>
              </td>
            </tr>
          )
        })}
      </tbody>
    </table>
    </div>
  )
}
