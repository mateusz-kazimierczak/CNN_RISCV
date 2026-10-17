import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import {
  existsSync,
  createReadStream,
  mkdirSync,
  copyFileSync,
  writeFileSync,
} from "node:fs";
import { resolve } from "node:path";

// Only this explicitly configured asset is exposed. No arbitrary repo filesystem access.
const configuration = process.env.PROFILE_CONFIGURATION || "B0";
if (!/^[A-Za-z0-9_-]+$/.test(configuration))
  throw new Error("Invalid profile configuration");
const bundle = resolve("..", "build", "explorer", `${configuration}.zip`);
function localAssets(server: { middlewares: { use: Function } }) {
  server.middlewares.use(
    (
      req: { url?: string },
      res: { setHeader: Function; end: Function; statusCode: number },
      next: Function,
    ) => {
      if (req.url === "/local-profile.json") {
        res.setHeader("Content-Type", "application/json");
        res.setHeader("Cache-Control", "no-store");
        res.end(
          JSON.stringify({
            available: existsSync(bundle),
            configuration,
            url: "/profiles/local.zip",
          }),
        );
      } else if (req.url === "/profiles/local.zip" && existsSync(bundle)) {
        res.setHeader("Content-Type", "application/zip");
        res.setHeader("Cache-Control", "no-store");
        createReadStream(bundle).pipe(res as never);
      } else next();
    },
  );
}
export default defineConfig({
  base: "./",
  plugins: [
    react(),
    {
      name: "explicit-local-profile",
      configureServer: localAssets,
      configurePreviewServer(server) {
        // Optional portable assets in dist take precedence over local configuration.
        if (!existsSync(resolve("dist/local-profile.json")))
          localAssets(server);
      },
      closeBundle() {
        if (process.env.EXPLORER_INCLUDE_BUNDLE === "1") {
          if (!existsSync(bundle))
            throw new Error(`Export bundle first: ${bundle}`);
          mkdirSync("dist/profiles", { recursive: true });
          copyFileSync(bundle, "dist/profiles/local.zip");
          writeFileSync(
            "dist/local-profile.json",
            JSON.stringify({
              available: true,
              configuration,
              url: "./profiles/local.zip",
            }),
          );
        }
      },
    },
  ],
  build: {
    target: "es2022",
    chunkSizeWarningLimit: 3000,
    rollupOptions: {
      input: {
        explorer: resolve("index.html"),
        simulator: resolve("simulator.html"),
      },
      output: {
        manualChunks(id) {
          if (id.includes("/elkjs/")) return "graph-layout";
          if (id.includes("/monaco-editor/")) return "code-editor";
        },
      },
    },
  },
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    proxy: { "/api/simulator": { target: "http://127.0.0.1:8765", ws: true } },
  },
  preview: { host: "127.0.0.1", port: 4173, strictPort: true },
});
