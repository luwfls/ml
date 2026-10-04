import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue2';

const backendTarget = process.env.VITE_WORKBENCH_API_TARGET || 'http://127.0.0.1:8765';

export default defineConfig({
  plugins: [vue()],
  root: '.',
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': {
        target: backendTarget,
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist/workbench',
    emptyOutDir: true,
  },
});
