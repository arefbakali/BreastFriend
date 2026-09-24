import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// En développement, /api et /static sont redirigés vers Flask (port 5000).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:5000",
      "/static": "http://127.0.0.1:5000",
    },
  },
});
