import { defineConfig } from "vitest/config";
import { resolve } from "node:path";

export default defineConfig({
  // Vite root is the frontend/ directory so index.html is found at frontend/public/index.html
  root: resolve(__dirname),
  publicDir: "public",
  envPrefix: "VITE_",
  build: {
    // Output relative to repo root: frontend/dist/
    outDir: resolve(__dirname, "..", "frontend", "dist"),
    emptyOutDir: true,
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./tests/setup.ts"],
    coverage: {
      provider: "v8",
      reportsDirectory: "./coverage",
      include: ["src/**"],
    },
  },
});
