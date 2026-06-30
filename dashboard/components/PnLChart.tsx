'use client'

import { useEffect, useRef } from 'react'
import type { IChartApi, ISeriesApi, UTCTimestamp } from 'lightweight-charts'

export interface EquityPoint {
  time: UTCTimestamp
  value: number
}

interface PnLChartProps {
  data: EquityPoint[]
  height?: number
}

export function PnLChart({ data, height = 300 }: PnLChartProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const seriesRef = useRef<ISeriesApi<'Baseline'> | null>(null)
  const roRef = useRef<ResizeObserver | null>(null)
  // Always current via ref so the async init closure reads the latest value
  const dataRef = useRef(data)
  dataRef.current = data

  // Initialize chart (runs once per height change; async import is guarded with cancelled flag)
  useEffect(() => {
    if (!containerRef.current) return
    let cancelled = false

    import('lightweight-charts').then((lib) => {
      if (cancelled || !containerRef.current) return
      const { createChart, ColorType, BaselineSeries } = lib

      const styles = getComputedStyle(document.documentElement)
      const muted = styles.getPropertyValue('--muted-foreground').trim() || '#8e8e93'
      const border = styles.getPropertyValue('--border').trim() || '#e5e5ea'

      const chart = createChart(containerRef.current!, {
        width: containerRef.current!.offsetWidth,
        height,
        layout: {
          background: { type: ColorType.Solid, color: 'transparent' },
          textColor: muted,
          fontFamily: '"JetBrains Mono", monospace',
          fontSize: 11,
        },
        grid: {
          vertLines: { color: 'transparent' },
          horzLines: { color: border },
        },
        crosshair: {
          vertLine: { visible: true, labelVisible: true },
          horzLine: { visible: true, labelVisible: true },
        },
        rightPriceScale: { borderColor: 'transparent', textColor: muted },
        timeScale: {
          borderColor: 'transparent',
          timeVisible: true,
          secondsVisible: false,
        },
        handleScroll: false,
        handleScale: false,
      })

      const series = chart.addSeries(BaselineSeries, {
        baseValue: { type: 'price', price: 0 },
        topLineColor: '#34c759',
        topFillColor1: 'rgba(52,199,89,0.28)',
        topFillColor2: 'rgba(52,199,89,0.04)',
        bottomLineColor: '#ff3b30',
        bottomFillColor1: 'rgba(255,59,48,0.04)',
        bottomFillColor2: 'rgba(255,59,48,0.24)',
        lineWidth: 2,
        crosshairMarkerVisible: true,
        crosshairMarkerRadius: 5,
        lastValueVisible: true,
        priceLineVisible: false,
        priceFormat: { type: 'price', precision: 2, minMove: 0.01 },
      })

      chartRef.current = chart
      seriesRef.current = series as unknown as ISeriesApi<'Baseline'>

      const init = dataRef.current
      if (init.length > 0) {
        series.setData(init as never)
        chart.timeScale().fitContent()
      }

      // Resize observer — stored in ref so cleanup below can disconnect it
      const ro = new ResizeObserver(() => {
        if (containerRef.current && chartRef.current) {
          chartRef.current.resize(containerRef.current.offsetWidth, height)
        }
      })
      ro.observe(containerRef.current!)
      roRef.current = ro
    })

    return () => {
      cancelled = true
      roRef.current?.disconnect()
      roRef.current = null
      chartRef.current?.remove()
      chartRef.current = null
      seriesRef.current = null
    }
  }, [height]) // eslint-disable-line react-hooks/exhaustive-deps

  // Live data updates — called whenever equity curve changes
  useEffect(() => {
    if (!seriesRef.current) return
    seriesRef.current.setData(data as never)
    if (data.length > 0 && chartRef.current) {
      chartRef.current.timeScale().fitContent()
    }
  }, [data])

  return <div ref={containerRef} style={{ height, width: '100%' }} />
}
