import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 開発中(npm run dev)は 5173 番で動き、/api は FastAPI(8000) に転送する。
// 本番(npm run build)は dist/ に出力し、FastAPI がそのまま配信する。
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:8000',
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
})
