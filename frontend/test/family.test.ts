/**
 * A family is not a recipe.
 *
 * It groups siblings for browsing and nothing resolves through one, so it must
 * never reach the screen as a thing to tap. Two halves, because either one alone
 * leaves the hole open: the picker does not draw it as a control, and the source
 * refuses the id if something else ever hands it one.
 */

import { describe, expect, it } from "vitest";
import "../src/elements/picker.js";
import type { RecipeWizardPicker } from "../src/elements/picker.js";
import { deepQuery, fixtureSource, library, settle, shadowText } from "./support.js";

describe("a family", () => {
  it("is drawn as a heading and never as a choosable row", async () => {
    const picker = document.createElement("recipe-wizard-picker") as RecipeWizardPicker;
    picker.index = library;
    document.body.replaceChildren(picker);
    await settle(picker);

    const family = library.families[0]!;
    expect(shadowText(picker)).toContain(family.name);

    const labels = deepQuery<HTMLButtonElement>(picker, "button").map((element) =>
      (element.textContent ?? "").trim(),
    );
    expect(labels).not.toContain(family.name);
    expect(labels).not.toContain(family.id);
    // Its members are still choosable, each on its own.
    expect(labels).toContain("Vanilla Buttercream");
  });

  it("is refused by the source if an id ever gets that far", async () => {
    const { source } = fixtureSource();
    await expect(source.start(library.families[0]!.id, 1)).rejects.toThrow(/not a recipe/);
    expect(source.cursor().status).toBe("idle");
  });

  it("does not swallow a recipe that belongs to no family", async () => {
    const picker = document.createElement("recipe-wizard-picker") as RecipeWizardPicker;
    picker.index = library;
    document.body.replaceChildren(picker);
    await settle(picker);

    const grouped = new Set(library.families.flatMap((family) => family.members));
    const loose = library.recipes.filter((recipe) => !grouped.has(recipe.id));
    const labels = deepQuery<HTMLButtonElement>(picker, "button").map((element) =>
      (element.textContent ?? "").trim(),
    );
    for (const recipe of loose) expect(labels).toContain(recipe.name);
  });
});
