import type { ReactNode } from 'react'

type Variant = 'default' | 'live' | 'warn' | 'success'

interface BadgeProps {
  variant?: Variant
  children: ReactNode
}

export function Badge({ variant = 'default', children }: BadgeProps) {
  return (
    <span className={`badge${variant !== 'default' ? ` ${variant}` : ''}`}>
      {children}
    </span>
  )
}
