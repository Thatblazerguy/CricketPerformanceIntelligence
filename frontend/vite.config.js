import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: true,
    proxy: {
      '/api': {
        // Override to point a second dev server at another API instance.
        target: process.env.CPI_API_PROXY || 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
});
