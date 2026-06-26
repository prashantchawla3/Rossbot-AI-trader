'use client'

import { useState } from 'react'
import { Power, Pause, Play, Loader } from 'lucide-react'
import { api } from '@/lib/api'
import { useDashboard } from '@/hooks/useDashboardState'

export function KillSwitch() {
  const { state, refetch } = useDashboard()
  const risk = state.data?.risk
  const [loading, setLoading] = useState<'kill' | 'pause' | 'resume' | null>(null)

  async function handle(action: 'kill' | 'pause' | 'resume') {
    setLoading(action)
    try {
      if (action === 'kill') await api.killSwitch()
      else if (action === 'pause') await api.pause()
      else await api.resume()
      await refetch()
    } catch {
      // alert_svc fires server-side; silent here
    } finally {
      setLoading(null)
    }
  }

  const isHalted = risk?.is_halted ?? false
  const isPaused = risk?.is_paused ?? false

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
      {!isHalted && !isPaused && (
        <button
          className="btn secondary"
          onClick={() => handle('pause')}
          disabled={loading !== null}
          title="Pause — stops new entries, holds positions"
        >
          {loading === 'pause' ? (
            <Loader size={13} className="animate-spin" />
          ) : (
            <Pause size={13} />
          )}
          Pause
        </button>
      )}

      {isPaused && !isHalted && (
        <button
          className="btn secondary"
          onClick={() => handle('resume')}
          disabled={loading !== null}
          title="Resume trading"
        >
          {loading === 'resume' ? (
            <Loader size={13} className="animate-spin" />
          ) : (
            <Play size={13} />
          )}
          Resume
        </button>
      )}

      <button
        className="btn danger"
        onClick={() => {
          if (!confirm('Flatten all positions and halt for the day?')) return
          handle('kill')
        }}
        disabled={loading !== null || isHalted}
        title="Kill switch — flatten all positions, halt session"
      >
        {loading === 'kill' ? (
          <Loader size={13} className="animate-spin" />
        ) : (
          <Power size={13} />
        )}
        {isHalted ? 'Halted' : 'Kill Switch'}
      </button>
    </div>
  )
}
