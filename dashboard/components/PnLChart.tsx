'use client'

import { useEffect, useRef } from 'react'
import type { IChartApi, ISeriesApi, LineData } from 'lightweight-charts'

interface PnLChartProps {
  data: LineData[]
  height?: number
}

export function PnLChart({ data, height = 140 }: PnLChartProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const seriesRef = useRef<ISeriesApi<'Line'> | null>(null)

  useEffect(() => {
    if (!containerRef.current) return

    let chart: IChartApi
    let series: ISeriesApi<'Line'>

    import('lightweight-charts').then(({ createChart, ColorType }) => {
      if (!containerRef.current) return

      const root = getComputedStyle(document.documentElement)
      const fg = root.getPropertyValue('--foreground').trim() || '#18181b'
      const muted = root.getPropertyValue('--muted-foreground').trim() || '#71717a'
      const border = root.getPropertyValue('--border').trim() || '#e4e4e7'
      const success = root.getPropertyValue('--success').trim() || '#16a34a'
      const danger = root.getPropertyValue('--destructive').trim() || '#dc2626'

      chart = createChart(containerRef.current!, {
        width: containerRef.current!.offsetWidth,
        height,
        layout: {
          background: { type: ColorType.Solid, color: 'transparent' },
          textColor: muted,
          fontFamily: 'Geist Mono, monospace',
          fontSize: 11,
        },
        grid: {
          vertLines: { color: 'transparent' },
          horzLines: { color: border },
        },
        crosshair: { vertLine: { visible: false } },
        rightPriceScale: {
          borderColor: 'transparent',
          textColor: muted,
        },
        timeScale: {
          borderColor: 'transparent',
          textColor: muted,
          timeVisible: true,
          secondsVisible: false,
        },
        handleScroll: false,
        handleScale: false,
      })

      series = chart.addSeries(
        // @ts-expect-error lightweight-charts v5 addSeries API
        { seriesType: 'Line' },
        {
          color: fg,
          lineWidth: 1.5,
          crosshairMarkerVisible: true,
          crosshairMarkerRadius: 4,
          lastValueVisible: true,
          priceLineVisible: false,
        },
      )
      series.setData(data)

      chartRef.current = chart
      seriesRef.current = series

      const ro = new ResizeObserver(() => {
        if (containerRef.current) {
          chart.resize(containerRef.current.offsetWidth, height)
        }
      })
      ro.observe(containerRef.current!)

      return () => ro.disconnect()
    })

    return () => {
      chartRef.current?.remove()
      chartRef.current = null
      seriesRef.current = null
    }
  }, [height])

  useEffect(() => {
    if (!seriesRef.current) return
    seriesRef.current.setData(data)
  }, [data])

  return <div ref={containerRef} className="chart-wrap" style={{ height }} />
}
