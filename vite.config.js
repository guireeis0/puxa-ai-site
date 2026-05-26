import { resolve } from 'path'
import { defineConfig } from 'vite'
import { fileURLToPath } from 'url'

const __dirname = fileURLToPath(new URL('.', import.meta.url))

export default defineConfig({
  server: {
    port: 5174,
    proxy: {
      '/upload':   'http://localhost:5000',
      '/status':   'http://localhost:5000',
      '/download': 'http://localhost:5000',
      '/health':   'http://localhost:5000',
      '/var':      'http://localhost:5000',
    },
  },
  build: {
    rollupOptions: {
      input: {
        main: resolve(__dirname, 'index.html'),
        var: resolve(__dirname, 'var.html'),
        analisar: resolve(__dirname, 'analisar.html'),
      },
    },
  },
})
