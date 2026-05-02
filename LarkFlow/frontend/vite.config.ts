import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

import larkSrcPlugin from "./vite-plugin-lark-src";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const backend = env.VITE_API_BASE ?? "http://127.0.0.1:8000";
  console.log("[vite.config] loaded, proxying /pipelines /visual-edits /metrics /healthz to", backend);
  // D6 圈选功能：仅在 dev 模式往 JSX host 元素注入 data-lark-src，生产构建保持洁净。
  const babelPlugins = mode === "development" ? [larkSrcPlugin] : [];
  return {
    plugins: [react({ babel: { plugins: babelPlugins } })],
    server: {
      port: 4173,
      proxy: {
        "/pipelines": { target: backend, changeOrigin: true },
        "/visual-edits": { target: backend, changeOrigin: true },
        "/metrics": { target: backend, changeOrigin: true },
        "/healthz": { target: backend, changeOrigin: true },
      },
    },
  };
});
