/**
 * The committed artifact, not the source that produced it.
 *
 * `custom_components/recipe_wizard/www/recipe-wizard.js` is what Home Assistant
 * actually loads, and the two element names in it are a contract with the Python
 * half: the panel is registered against `recipe-wizard-panel` and the dashboard
 * looks up `recipe-wizard-card`. Both are strings, in two languages, in two
 * directories -- so a rename that compiles cleanly can still leave a blank page.
 * This imports the built file and checks that loading it defines them.
 *
 * It reads the bundle rather than importing `src/index.ts` on purpose: a build
 * configuration that tree-shook a registration away, or split the output in two,
 * would pass every other test in here.
 */

import { describe, expect, it } from "vitest";

describe("the built bundle", () => {
  it("defines both mounts, and the card announces itself to the picker", async () => {
    // Untyped on purpose: the bundle ships no declarations, and this test is
    // about what loading it *does* rather than about its exports.
    await import(
      /* @vite-ignore */ "../../custom_components/recipe_wizard/www/recipe-wizard.js" as string
    );

    expect(customElements.get("recipe-wizard-panel")).toBeTypeOf("function");
    expect(customElements.get("recipe-wizard-card")).toBeTypeOf("function");
    expect(customElements.get("recipe-wizard-surface")).toBeTypeOf("function");

    const cards = (window as unknown as Record<string, unknown>)["customCards"] as {
      type: string;
    }[];
    expect(cards.map((card) => card.type)).toContain("recipe-wizard-card");
  });
});
