'use client'

import { Info } from 'lucide-react'
import type { ReactNode } from 'react'

interface TooltipProps {
  label: string
  children: ReactNode
  side?: 'top' | 'bottom'
}

/**
 * Plain-language hint shown on hover / keyboard-focus / tap.
 * Wrap any element to explain what it means in simple terms.
 */
export function Tooltip({ label, children, side = 'top' }: TooltipProps) {
  return (
    <span className="tip" tabIndex={0}>
      {children}
      <span className={`tip-bubble${side === 'bottom' ? ' bottom' : ''}`} role="tooltip">
        {label}
      </span>
    </span>
  )
}

/**
 * Small "ⓘ" icon that reveals a short explanation on hover/focus.
 * Use next to labels the user might not understand.
 */
export function InfoHint({ label, size = 13 }: { label: string; size?: number }) {
  return (
    <Tooltip label={label}>
      <span className="info-hint" aria-label={label}>
        <Info size={size} />
      </span>
    </Tooltip>
  )
}
