import { defineConfig } from "vite";

// One self-contained ES module; HA loads it via panel_custom module_url.
export default defineConfig({
  build: {
    outDir: "../custom_components/garmin_dashboard/www",
    emptyOutDir: true,
    target: "es2022",
    lib: {
      entry: "src/panel.ts",
      formats: ["es"],
      fileName: () => "garmin-dashboard-panel.js",
    },
  },
});
