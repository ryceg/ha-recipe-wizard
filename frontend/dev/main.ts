/** Wires the fixture source into the page, and nothing else. */
import "../src/elements/surface.js";
import { FixtureCookAlongSource } from "../src/fixture-source.js";
import { SystemClock } from "../src/clock.js";
import type { RecipeWizardSurface } from "../src/elements/surface.js";
import type { Dish, LibraryIndex } from "../src/payload.js";
import library from "../fixtures/library.json";
import vanillaCake from "../fixtures/vanilla-cake.json";

const source = new FixtureCookAlongSource(
  library as LibraryIndex,
  { [(vanillaCake as unknown as Dish).id]: vanillaCake as unknown as Dish },
  new SystemClock(),
);

const surface = document.getElementById("surface") as RecipeWizardSurface;
surface.source = source;
surface.clock = new SystemClock();
