import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Inside compose the API is another container; on a laptop it is localhost.
const apiTarget = process.env.VITE_API_PROXY ?? 'http://localhost:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5173,
    proxy: {
      '/api': { target: apiTarget, changeOrigin: true },
    },
  },
})
