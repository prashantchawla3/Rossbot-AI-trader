import type { Metadata } from 'next'
import { GeistSans } from 'geist/font/sans'
import { GeistMono } from 'geist/font/mono'
import { DM_Serif_Display } from 'next/font/google'
import './globals.css'

const dmSerifDisplay = DM_Serif_Display({
  weight: '400',
  style: ['normal', 'italic'],
  variable: '--font-dm-serif',
  display: 'swap',
  subsets: ['latin'],
})

export const metadata: Metadata = {
  title: 'RossBot — Trading Dashboard',
  description: 'Live monitoring and control for RossBot automated trading system',
  robots: 'noindex, nofollow',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="en"
      className={`${GeistSans.variable} ${GeistMono.variable} ${dmSerifDisplay.variable}`}
      suppressHydrationWarning
    >
      <body>{children}</body>
    </html>
  )
}
