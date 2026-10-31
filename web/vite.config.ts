import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { refreshPlugin } from './refreshPlugin.ts'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), refreshPlugin()],
})
