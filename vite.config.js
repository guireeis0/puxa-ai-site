import { resolve } from 'path'
import { defineConfig } from 'vite'
import { fileURLToPath } from 'url'

const __dirname = fileURLToPath(new URL('.', import.meta.url))

export default defineConfig({
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
