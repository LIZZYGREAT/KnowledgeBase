import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "KB_");
  const apiProxy = {
    "/api": {
      target: env.KB_API_PROXY_TARGET || "http://127.0.0.1:8000",
      changeOrigin: true,
    },
  };

  return {
    plugins: [react()],
    server: { proxy: apiProxy },
    preview: { proxy: apiProxy },
  };
});
