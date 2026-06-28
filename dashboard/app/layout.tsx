import type { Metadata } from 'next'
import { DM_Sans, JetBrains_Mono } from 'next/font/google'
import './globals.css'

// Pinguo / Apple-inspired type system: DM Sans for UI, JetBrains Mono for data.
const dmSans = DM_Sans({
  weight: ['400', '500', '600', '700'],
  variable: '--font-dm-sans',
  display: 'swap',
  subsets: ['latin'],
})

const jetBrainsMono = JetBrains_Mono({
  weight: ['400', '500'],
  variable: '--font-jetbrains',
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
      className={`${dmSans.variable} ${jetBrainsMono.variable}`}
      suppressHydrationWarning
    >
      <body>{children}</body>
    </html>
  )
}
