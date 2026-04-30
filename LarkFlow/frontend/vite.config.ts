import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const backend = env.VITE_API_BASE ?? "http://127.0.0.1:8000";
  console.log("[vite.config] loaded, proxying /pipelines /metrics /healthz to", backend);
  return {
    plugins: [react()],
    server: {
      port: 4173,
      proxy: {
        "/pipelines": { target: backend, changeOrigin: true },
        "/metrics": { target: backend, changeOrigin: true },
        "/healthz": { target: backend, changeOrigin: true },
      },
    },
  };
});
