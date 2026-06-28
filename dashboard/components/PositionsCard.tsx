import type { OpenPosition } from '@/lib/types'
import { InfoHint } from './Tooltip'

interface PositionsCardProps {
  positions: OpenPosition[]
}

function pnlSentiment(pnl: string) {
  const n = parseFloat(pnl)
  if (n > 0) return 'positive'
  if (n < 0) return 'negative'
  return 'neutral'
}

export function PositionsCard({ positions }: PositionsCardProps) {
  if (positions.length === 0) {
    return <p className="empty-state">No open positions right now</p>
  }

  return (
    <div className="table-wrap">
    <table className="table">
      <thead>
        <tr>
          <th>Symbol</th>
          <th>Shares</th>
          <th>Avg</th>
          <th>Last</th>
          <th>
            <span className="eyebrow" style={{ gap: '4px' }}>
              Unreal. P&L
              <InfoHint label="Profit or loss if you sold this position right now, at the current price. Not yet locked in." />
            </span>
          </th>
        </tr>
      </thead>
      <tbody>
        {positions.map((p) => {
          const sentiment = pnlSentiment(p.unrealised_pnl)
          return (
            <tr key={p.symbol}>
              <td>
                <strong>{p.symbol}</strong>
              </td>
              <td className="mono">{p.shares.toLocaleString()}</td>
              <td className="mono">${p.avg_price}</td>
              <td className="mono">${p.current_price}</td>
              <td>
                <span
                  className="mono"
                  style={{
                    color:
                      sentiment === 'positive'
                        ? 'var(--success)'
                        : sentiment === 'negative'
                          ? 'var(--destructive)'
                          : 'inherit',
                  }}
                >
                  ${p.unrealised_pnl}
                </span>
              </td>
            </tr>
          )
        })}
      </tbody>
    </table>
    </div>
  )
}
