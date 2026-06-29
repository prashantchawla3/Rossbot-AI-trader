'use client'

import {
  createContext,
  useContext,
  useReducer,
  useCallback,
  useEffect,
  type ReactNode,
} from 'react'
import { useWebSocket } from './useWebSocket'
import { api } from '@/lib/api'
import type { DashboardState, WsMessage, SignalEvent, RiskEvent, CatalystUpdateEvent } from '@/lib/types'

type Status = 'connecting' | 'live' | 'error'

interface State {
  data: DashboardState | null
  status: Status
  lastUpdated: Date | null
  catalystAlerts: CatalystUpdateEvent[]
}

type Action =
  | { type: 'SET_STATE'; payload: DashboardState }
  | { type: 'PREPEND_SIGNAL'; payload: SignalEvent }
  | { type: 'PREPEND_RISK_EVENT'; payload: RiskEvent }
  | { type: 'SET_STATUS'; status: Status }
  | { type: 'CATALYST_UPDATE'; payload: CatalystUpdateEvent }

function reducer(state: State, action: Action): State {
  switch (action.type) {
    case 'SET_STATE':
      return { ...state, data: action.payload, status: 'live', lastUpdated: new Date() }
    case 'PREPEND_SIGNAL':
      if (!state.data) return state
      return {
        ...state,
        data: {
          ...state.data,
          recent_signals: [action.payload, ...state.data.recent_signals].slice(0, 200),
        },
      }
    case 'PREPEND_RISK_EVENT':
      if (!state.data) return state
      return {
        ...state,
        data: {
          ...state.data,
          recent_risk_events: [action.payload, ...state.data.recent_risk_events].slice(0, 500),
        },
      }
    case 'SET_STATUS':
      return { ...state, status: action.status }
    case 'CATALYST_UPDATE':
      return {
        ...state,
        catalystAlerts: [action.payload, ...state.catalystAlerts].slice(0, 50),
      }
    default:
      return state
  }
}

const DashboardContext = createContext<{
  state: State
  refetch: () => void
} | null>(null)

export function DashboardProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(reducer, {
    data: null,
    status: 'connecting',
    lastUpdated: null,
    catalystAlerts: [],
  })

  const refetch = useCallback(async () => {
    try {
      const data = await api.getState()
      dispatch({ type: 'SET_STATE', payload: data })
    } catch {
      dispatch({ type: 'SET_STATUS', status: 'error' })
    }
  }, [])

  useEffect(() => {
    refetch()
  }, [refetch])

  const handleMessage = useCallback((msg: WsMessage) => {
    if (msg.type === 'state_update') {
      dispatch({ type: 'SET_STATE', payload: msg.payload as DashboardState })
    } else if (msg.type === 'signal') {
      dispatch({ type: 'PREPEND_SIGNAL', payload: msg.payload as SignalEvent })
    } else if (msg.type === 'risk_event') {
      dispatch({ type: 'PREPEND_RISK_EVENT', payload: msg.payload as RiskEvent })
    } else if (msg.type === 'catalyst_update') {
      dispatch({ type: 'CATALYST_UPDATE', payload: msg.payload as CatalystUpdateEvent })
    }
  }, [])

  useWebSocket(handleMessage)

  return (
    <DashboardContext.Provider value={{ state, refetch }}>
      {children}
    </DashboardContext.Provider>
  )
}

export function useDashboard() {
  const ctx = useContext(DashboardContext)
  if (!ctx) throw new Error('useDashboard must be used inside DashboardProvider')
  return ctx
}
