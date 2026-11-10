/// <reference types="vitest" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// ビルドした画面は BFF（proactive_web）が配る。開発中は /api を BFF に回す
export default defineConfig({
  plugins: [react()],
  build: { outDir: "../proactive_web/static", emptyOutDir: true },
  server: { proxy: { "/api": "http://127.0.0.1:8000" } },
  test: { environment: "node" },
});
