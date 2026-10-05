import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue2';

export default defineConfig({
  plugins: [vue()],
  server: {
    strictPort: true,
    proxy: Object.fromEntries(['/api', '/captures', '/assets'].map(path => [path, 'http://127.0.0.1:8765'])),
  },
  build: { outDir: 'dist/workbench' },
});
