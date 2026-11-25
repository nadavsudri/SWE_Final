import { defineConfig } from "vite";

// Dev: `npm run dev` proxies the API to `python -m leg.api` on :8000.
export default defineConfig({
  server: { proxy: { "/api": "http://127.0.0.1:8000" } },
  build: { outDir: "dist", chunkSizeWarningLimit: 1500 },
});
