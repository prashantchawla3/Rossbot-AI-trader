import type { NextConfig } from 'next'

const config: NextConfig = {
  // Turbopack is default in Next.js 16; no flag needed for next dev
  // Strict mode catches hydration issues early
  reactStrictMode: true,
}

export default config
