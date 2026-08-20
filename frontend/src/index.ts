/**
 * The one file Home Assistant loads: both mounts, one bundle.
 *
 * The panel and the card are registered from the same module because they are
 * the same screen and there is nothing to be gained by making a dashboard fetch
 * one half of it. The bundle is served from `/recipe_wizard_static` and lands on
 * disk at `custom_components/recipe_wizard/www/recipe-wizard.js`, committed,
 * because HACS installs by copying that directory and there is no build step at
 * the far end.
 */

import "./panel.js";
import "./card.js";

export { RecipeWizardPanel } from "./panel.js";
export { RecipeWizardCard } from "./card.js";
export { RecipeWizardSurface } from "./elements/surface.js";
export { HassCookAlongSource } from "./hass-source.js";
export { FixtureCookAlongSource } from "./fixture-source.js";
export { SystemClock, ManualClock } from "./clock.js";
export type { Clock, CookAlongSource, CursorState } from "./ports.js";

interface CustomCard {
  type: string;
  name: string;
  description: string;
  preview?: boolean;
}

// How the card picker finds it. Guarded because this module is also imported by
// the dev server and the test suite, where there is no dashboard.
const cards: CustomCard[] = ((window as unknown as Record<string, unknown>)["customCards"] ??=
  []) as CustomCard[];
if (!cards.some((card) => card.type === "recipe-wizard-card")) {
  cards.push({
    type: "recipe-wizard-card",
    name: "Recipe Wizard cook-along",
    description: "Cook along with a recipe: one step at a time, at your batch size.",
  });
}
