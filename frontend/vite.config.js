import {defineConfig} from 'vite';
import vue from '@vitejs/plugin-vue';

export default defineConfig({
  base: '/static/vue/',
  plugins: [vue({template:{transformAssetUrls:false}})],
  server: {port: 5173, strictPort:true, proxy: {
    // Preserve Host + Origin together so the backend keeps its origin check.
    '/api': {target: 'http://127.0.0.1:8765', changeOrigin: false},
    '/static/assets': 'http://127.0.0.1:8765',
    '/static/fonts': 'http://127.0.0.1:8765',
    '/static/vendor': 'http://127.0.0.1:8765',
  }},
  build: {target: 'es2022'},
  test: {environment: 'jsdom', include: ['src/**/*.test.js'], restoreMocks: true},
});
