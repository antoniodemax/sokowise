import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // Local development proxies the API through the Vite origin so the HttpOnly
    // refresh cookie is same-origin (docs/ARCHITECTURE.md §5.1). Production and
    // preview deployments call the API origin directly.
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
})
