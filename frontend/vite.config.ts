/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

// Adapted from Eval Lab's same-origin FastAPI / Vite setup (MIT).
export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1', port: 5173, strictPort: true,
    proxy: { '/api': { target: 'http://127.0.0.1:8766', changeOrigin: false } },
  },
  build: { outDir: 'dist', emptyOutDir: true, sourcemap: false, cssCodeSplit: false },
  test: { globals: true, environment: 'jsdom', setupFiles: ['./src/test/setup.ts'], include: ['src/test/**/*.test.{ts,tsx}'], css: false, restoreMocks: true },
});
