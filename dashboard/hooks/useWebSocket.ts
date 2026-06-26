'use client'

import { useEffect, useRef, useCallback } from 'react'
import type { WsMessage } from '@/lib/types'

const WS_URL = process.env.NEXT_PUBLIC_WS_URL ?? 'ws://localhost:8000'
const PING_INTERVAL_MS = 25_000
const RECONNECT_DELAY_MS = 3_000

type Handler = (msg: WsMessage) => void

export function useWebSocket(onMessage: Handler) {
  const wsRef = useRef<WebSocket | null>(null)
  const pingRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const reconnectRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const onMessageRef = useRef<Handler>(onMessage)
  const unmountedRef = useRef(false)

  // Always call the latest handler without re-connecting
  useEffect(() => {
    onMessageRef.current = onMessage
  })

  const connect = useCallback(() => {
    if (unmountedRef.current) return

    const ws = new WebSocket(`${WS_URL}/ws/live`)
    wsRef.current = ws

    ws.onopen = () => {
      pingRef.current = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: 'ping' }))
        }
      }, PING_INTERVAL_MS)
    }

    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data as string) as WsMessage
        if (msg.type !== 'pong') {
          onMessageRef.current(msg)
        }
      } catch {
        // malformed frame — ignore
      }
    }

    ws.onclose = () => {
      if (pingRef.current) {
        clearInterval(pingRef.current)
        pingRef.current = null
      }
      if (!unmountedRef.current) {
        reconnectRef.current = setTimeout(connect, RECONNECT_DELAY_MS)
      }
    }

    ws.onerror = () => {
      ws.close()
    }
  }, [])

  useEffect(() => {
    unmountedRef.current = false
    connect()

    return () => {
      unmountedRef.current = true
      if (reconnectRef.current) clearTimeout(reconnectRef.current)
      if (pingRef.current) clearInterval(pingRef.current)
      wsRef.current?.close()
    }
  }, [connect])
}
