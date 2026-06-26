import { DashboardProvider } from '@/hooks/useDashboardState'
import { Sidebar } from '@/components/Sidebar'

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return (
    <DashboardProvider>
      <div className="dashboard-frame">
        <Sidebar />
        <main className="main">{children}</main>
      </div>
    </DashboardProvider>
  )
}
