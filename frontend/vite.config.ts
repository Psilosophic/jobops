import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: { "/api": { target: "http://localhost:8100", changeOrigin: true, rewrite: p => p.replace(/^\/api/, "") } },
  },
});
