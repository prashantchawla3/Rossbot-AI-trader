'use client'

import { createContext, useContext, useState, type ReactNode } from 'react'

interface ChartSymbolCtx {
  symbol: string // bare ticker, e.g. "MLGO"
  setSymbol: (s: string) => void
}

const Ctx = createContext<ChartSymbolCtx | null>(null)

export function ChartSymbolProvider({ children }: { children: ReactNode }) {
  const [symbol, setSymbol] = useState('AAPL')
  return (
    <Ctx.Provider value={{ symbol, setSymbol: (s) => setSymbol(s.toUpperCase().trim()) }}>
      {children}
    </Ctx.Provider>
  )
}

export function useChartSymbol() {
  const ctx = useContext(Ctx)
  if (!ctx) throw new Error('useChartSymbol must be used inside ChartSymbolProvider')
  return ctx
}
