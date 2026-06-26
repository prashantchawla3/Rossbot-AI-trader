'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import {
  LayoutDashboard,
  ScanSearch,
  Zap,
  AlertTriangle,
  BookOpen,
  Activity,
} from 'lucide-react'
import { useDashboard } from '@/hooks/useDashboardState'

const NAV = [
  { href: '/overview', label: 'Overview', icon: LayoutDashboard, caption: 'P&L + positions' },
  { href: '/watchlist', label: 'Watchlist', icon: ScanSearch, caption: 'Tier A / Tier B' },
  { href: '/signals', label: 'Signals', icon: Zap, caption: 'Entry / exit feed' },
  { href: '/risk-events', label: 'Risk Events', icon: AlertTriangle, caption: 'Vetoes + halts' },
  { href: '/journal', label: 'Journal', icon: BookOpen, caption: 'Post-session report' },
  { href: '/health', label: 'Health', icon: Activity, caption: 'Feeds + latency' },
] as const

export function Sidebar() {
  const pathname = usePathname()
  const { state } = useDashboard()
  const isHalted = state.data?.risk.is_halted ?? false

  return (
    <nav className="sidebar">
      <div className="brand">
        <span className="brand-mark">R</span>
        <div className="brand-copy">
          <strong>RossBot</strong>
          <small>Day-trade system</small>
        </div>
      </div>

      <div>
        <p className="nav-section-title">Navigation</p>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
          {NAV.map(({ href, label, icon: Icon, caption }) => (
            <Link
              key={href}
              href={href}
              className={`nav-item${pathname.startsWith(href) ? ' active' : ''}`}
            >
              <span className="nav-label">
                <Icon size={14} />
                {label}
              </span>
              <span className="nav-caption">{caption}</span>
            </Link>
          ))}
        </div>
      </div>

      <div className="sidebar-footer">
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span
            className={`status-dot ${isHalted ? 'disconnected' : 'connected'}`}
          />
          <span className="small muted">{isHalted ? 'Halted' : 'Live'}</span>
        </div>
      </div>
    </nav>
  )
}
