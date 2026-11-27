import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8766",
      "/files": "http://127.0.0.1:8766",
      "/healthz": "http://127.0.0.1:8766",
      "/readyz": "http://127.0.0.1:8766"
    }
  },
  build: {
    outDir: "../../opskestrel/console_static",
    emptyOutDir: true,
    sourcemap: false
  }
});
