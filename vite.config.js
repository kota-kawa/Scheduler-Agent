import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";
import { fileURLToPath } from "url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

export default defineConfig({
  root: path.resolve(__dirname, "frontend"),
  plugins: [react()],
  base: "./",
  build: {
    outDir: path.resolve(__dirname, "static/spa"),
    emptyOutDir: true,
    rollupOptions: {
      input: path.resolve(__dirname, "frontend/index.html"),
      output: {
        entryFileNames: "app.js",
        chunkFileNames: "chunk-[name].js",
        assetFileNames: (assetInfo) => {
          if (assetInfo.name && assetInfo.name.endsWith(".css")) {
            return "app.css";
          }
          return "asset-[name].[ext]";
        }
      }
    }
  },
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": "http://localhost:5000",
      "/model_settings": "http://localhost:5000"
    }
  }
});
