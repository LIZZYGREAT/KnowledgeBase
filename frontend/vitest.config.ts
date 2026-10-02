import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    include: ["tests/unit/**/*.test.ts", "tests/integration/**/*.test.tsx"],
    setupFiles: ["./tests/integration/setup.ts"],
    restoreMocks: true,
    clearMocks: true,
  },
});
