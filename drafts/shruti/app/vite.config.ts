import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// base './' so the built index.html loads assets via file:// inside Electron.
export default defineConfig({
  plugins: [react()],
  base: './',
  server: { host: '127.0.0.1' },
  build: { outDir: 'dist', emptyOutDir: true },
})
