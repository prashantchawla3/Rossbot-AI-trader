import { DashboardProvider } from '@/hooks/useDashboardState'
import { ChartSymbolProvider } from '@/hooks/useChartSymbol'
import { TopNav } from '@/components/TopNav'
import { StatusBar } from '@/components/StatusBar'

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return (
    <DashboardProvider>
      <ChartSymbolProvider>
        <div className="app-shell">
          <TopNav />
          <StatusBar />
          <main className="main">{children}</main>
        </div>
      </ChartSymbolProvider>
    </DashboardProvider>
  )
}
