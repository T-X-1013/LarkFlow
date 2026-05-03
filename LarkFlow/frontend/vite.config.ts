import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

import larkSrcPlugin from "./vite-plugin-lark-src";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const backend = env.VITE_API_BASE ?? "http://127.0.0.1:8000";
  console.log("[vite.config] loaded, proxying /pipelines /visual-edits /metrics /healthz to", backend);
  const bypassSpaNavigation = (req: { headers: Record<string, string | string[] | undefined> }) => {
    const accept = req.headers.accept;
    const value = Array.isArray(accept) ? accept.join(",") : (accept ?? "");
    return value.includes("text/html") ? "/index.html" : undefined;
  };
  // D6 圈选功能：仅在 dev 模式往 JSX host 元素注入 data-lark-src，生产构建保持洁净。
  const babelPlugins = mode === "development" ? [larkSrcPlugin] : [];
  return {
    plugins: [react({ babel: { plugins: babelPlugins } })],
    server: {
      port: 4173,
      proxy: {
        "/pipelines": { target: backend, changeOrigin: true, bypass: bypassSpaNavigation },
        "/visual-edits": { target: backend, changeOrigin: true, bypass: bypassSpaNavigation },
        "/metrics": { target: backend, changeOrigin: true, bypass: bypassSpaNavigation },
        "/healthz": { target: backend, changeOrigin: true, bypass: bypassSpaNavigation },
      },
    },
  };
});
