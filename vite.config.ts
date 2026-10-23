import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "node:path";

// Plain Vite + React SPA. `vite build` emits a static site to dist/.
// Deep links (e.g. /app) are served index.html via the rewrite in vercel.json.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") },
    dedupe: ["react", "react-dom"],
  },
  build: {
    outDir: "dist",
  },
});
