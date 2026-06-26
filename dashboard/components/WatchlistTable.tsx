'use client'

import { Badge } from './Badge'
import type { WatchlistEntry } from '@/lib/types'

interface WatchlistTableProps {
  entries: WatchlistEntry[]
  tier: 'A' | 'B'
}

export function WatchlistTable({ entries, tier }: WatchlistTableProps) {
  if (entries.length === 0) {
    return (
      <p className="small muted" style={{ textAlign: 'center', padding: '24px 0' }}>
        No Tier {tier} symbols yet
      </p>
    )
  }

  return (
    <table className="table">
      <thead>
        <tr>
          <th>Symbol</th>
          <th>Price</th>
          <th>RVOL</th>
          <th>Float</th>
          <th>Catalyst</th>
          <th>Pillars</th>
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
                <Badge variant={allPass ? 'success' : 'warn'}>
                  {pillarsPass}/{pillarsTotal}
                </Badge>
              </td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}
