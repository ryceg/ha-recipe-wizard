/**
 * One bundle, in a fixed place, byte-for-byte reproducible.
 *
 * The output is committed to ``custom_components/recipe_wizard/www/`` because
 * HACS installs by copying that directory out of the repository and there is no
 * build step at install time -- the same constraint that made the Python library
 * get vendored into ``core/``. A committed artifact goes stale silently, so CI
 * rebuilds it and fails on any difference; everything here that looks fussy is
 * in service of that check being meaningful:
 *
 * * ``entryFileNames`` is a literal, because a content hash in the filename
 *   would make every rebuild a new file and the panel's URL a moving target;
 * * ``cssCodeSplit`` is off and there are no assets -- Lit carries its styles in
 *   the module, so a second output file would be a surprise, not a feature.
 *   Nothing here imports dynamically either, so the bundle is one file without
 *   having to be told to be;
 * * nothing is externalised: Home Assistant serves this file on its own and
 *   there is no import map at the far end.
 */
// ``vitest/config`` rather than ``vite`` only so the ``test`` block below is
// typed. It re-exports Vite's own ``defineConfig``; the build is plain Vite.
import { defineConfig } from "vitest/config";

export default defineConfig({
  build: {
    target: "es2021",
    outDir: "../custom_components/recipe_wizard/www",
    emptyOutDir: false,
    cssCodeSplit: false,
    sourcemap: false,
    lib: {
      entry: "src/index.ts",
      formats: ["es"],
      fileName: () => "recipe-wizard.js",
    },
    rollupOptions: {
      output: {
        entryFileNames: "recipe-wizard.js",
        assetFileNames: "recipe-wizard-[name][extname]",
      },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    include: ["test/**/*.test.ts"],
  },
});
