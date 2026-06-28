'use client'

import type { ReactNode } from 'react'
import { Tooltip, InfoHint } from './Tooltip'
import { termHint } from '@/lib/glossary'

/** Wrap a technical term in a dotted-underline hover explanation. */
export function Term({ term, children }: { term: string; children?: ReactNode }) {
  return (
    <Tooltip label={termHint(term)}>
      <span className="term">{children ?? term}</span>
    </Tooltip>
  )
}

/** Standalone ⓘ icon explaining a glossary term. */
export function TermHint({ term }: { term: string }) {
  return <InfoHint label={termHint(term)} />
}
