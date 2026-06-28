'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { LayoutDashboard, ScanSearch, Zap, Brain, BookOpen } from 'lucide-react'
import { useDashboard } from '@/hooks/useDashboardState'
import { Tooltip } from './Tooltip'
import { KillSwitch } from './KillSwitch'

// Five operator-console tabs, each with a plain-language hint.
const NAV = [
  {
    href: '/command-center',
    label: 'Command',
    icon: LayoutDashboard,
    hint: 'Command center — bot controls, the risk gauge, and live status.',
  },
  {
    href: '/watchlist',
    label: 'Watchlist',
    icon: ScanSearch,
    hint: 'Stocks the bot is watching + the live chart. Tier B passed all 5 pillars; Tier A is the wider pool.',
  },
  {
    href: '/signals',
    label: 'Signals',
    icon: Zap,
    hint: 'Open positions (with controls) and the live feed of every buy / sell / skip decision.',
  },
  {
    href: '/analysis',
    label: 'AI Analysis',
    icon: Brain,
    hint: 'Ask the AI to grade any symbol against Ross’s rules, then trade it through the risk gate.',
  },
  {
    href: '/journal',
    label: 'Journal',
    icon: BookOpen,
    hint: 'Today’s completed trades, the session summary, and a plain-English rules reference.',
  },
] as const

export function TopNav() {
  const pathname = usePathname()
  const { state } = useDashboard()
  const risk = state.data?.risk

  const isHalted = risk?.is_halted ?? false
  const isPaused = risk?.is_paused ?? false
  const status = state.status

  let dotClass = 'live-dot pulse'
  let statusText = 'Live'
  let statusHint = 'Connected — receiving live market data and trading normally.'

  if (status === 'connecting') {
    dotClass = 'live-dot connecting'
    statusText = 'Connecting'
    statusHint = 'Trying to reach the trading server…'
  } else if (status === 'error') {
    dotClass = 'live-dot halted'
    statusText = 'Offline'
    statusHint = 'Lost connection to the trading server. Reconnecting automatically.'
  } else if (isHalted) {
    dotClass = 'live-dot halted'
    statusText = 'Halted'
    statusHint = `Trading stopped for the day${risk?.halt_reason ? `: ${risk.halt_reason}` : '.'}`
  } else if (isPaused) {
    dotClass = 'live-dot connecting'
    statusText = 'Paused'
    statusHint = 'No new trades; existing positions are still held.'
  }

  return (
    <header className="topnav">
      <div className="topnav-inner">
        <div className="topnav-brand">
          <span className="brand-mark">R</span>
          <div className="brand-copy">
            <strong>RossBot</strong>
            <small>Day-trade system</small>
          </div>
        </div>

        <nav className="topnav-rail" aria-label="Primary">
          {NAV.map(({ href, label, icon: Icon, hint }) => (
            <Tooltip key={href} label={hint} side="bottom">
              <Link
                href={href}
                className={`nav-link${pathname.startsWith(href) ? ' active' : ''}`}
                aria-current={pathname.startsWith(href) ? 'page' : undefined}
              >
                <Icon size={15} />
                {label}
              </Link>
            </Tooltip>
          ))}
        </nav>

        <div className="topnav-actions">
          <Tooltip label={statusHint} side="bottom">
            <span className="live-pill">
              <span className={dotClass} />
              {statusText}
            </span>
          </Tooltip>
          <KillSwitch />
        </div>
      </div>
    </header>
  )
}
