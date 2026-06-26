import type { Metadata } from 'next'
import { GeistSans } from 'geist/font/sans'
import { GeistMono } from 'geist/font/mono'
import localFont from 'next/font/local'
import './globals.css'

const dmSerifDisplay = localFont({
  src: [
    {
      path: '../public/fonts/DMSerifDisplay-Regular.woff2',
      weight: '400',
      style: 'normal',
    },
  ],
  variable: '--font-dm-serif',
  display: 'swap',
  fallback: ['Georgia', 'serif'],
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
