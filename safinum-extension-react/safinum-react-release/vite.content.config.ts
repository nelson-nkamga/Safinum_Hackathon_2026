// Build 2 : content script en un seul fichier IIFE, TypeScript natif, sans React.
import { defineConfig } from "vite";
import { resolve } from "node:path";

export default defineConfig({
  publicDir: false,
  build: {
    outDir: "dist",
    emptyOutDir: false,
    lib: {
      entry: resolve(__dirname, "src/content/index.ts"),
      formats: ["iife"],
      name: "SafinumContent",
      fileName: () => "content.js"
    }
  }
});
