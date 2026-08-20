/**
 * Test premises, built out of the real payloads.
 *
 * The fixtures are generated from the library itself, for the same reason
 * `tests/support.py` round-trips through `Recipe.parse`: a test written against a
 * payload shape invented here could assert behaviour that no dish the library
 * writes can produce. Regenerate them from the repository root rather than
 * editing them by hand:
 *
 * ```
 * python -m recipe_wizard --list --json > frontend/fixtures/library.json
 * python -m recipe_wizard vanilla-cake --batches 2 --json  *     > frontend/fixtures/vanilla-cake.json
 * ```
 *
 * That flag exists so the payload can be read without Home Assistant running,
 * and it is the same `serialise.py` the HTTP views call -- so a fixture cannot
 * drift from what the panel is actually served.
 *
 * `shadowText` and `deepQuery` reach through shadow roots because the surface is
 * three nested elements and a test that only looked at the outermost one would
 * pass while the screen was blank.
 */

import { FixtureCookAlongSource } from "../src/fixture-source.js";
import { ManualClock } from "../src/clock.js";
import type { Dish, LibraryIndex } from "../src/payload.js";
import libraryFixture from "../fixtures/library.json";
import cakeFixture from "../fixtures/vanilla-cake.json";

export const library = libraryFixture as unknown as LibraryIndex;
export const cake = cakeFixture as unknown as Dish;

export const CAKE_ID = cake.id;

export function fixtureSource(clock = new ManualClock(1_700_000_000_000)): {
  source: FixtureCookAlongSource;
  clock: ManualClock;
} {
  const source = new FixtureCookAlongSource(library, { [cake.id]: cake }, clock);
  return { source, clock };
}

/**
 * Every rendered word, shadow roots included, whitespace collapsed.
 *
 * Element boundaries become a space and text nodes do not, so `${position}/${of}`
 * -- three text nodes in one span -- reads back as `12/16` rather than
 * `12 / 16`. Stylesheets are skipped: the surface carries its CSS in the module,
 * and a test asserting a word is absent should not be able to trip over it in a
 * selector.
 */
export function shadowText(node: Node): string {
  const parts: string[] = [];
  const walk = (current: Node): void => {
    if (current.nodeType === 3) {
      parts.push(current.textContent ?? "");
      return;
    }
    if (current.nodeType === 1) {
      const element = current as Element;
      if (element.tagName === "STYLE") return;
      parts.push(" ");
      if (element.shadowRoot) walk(element.shadowRoot);
    }
    current.childNodes.forEach(walk);
    if (current.nodeType === 1) parts.push(" ");
  };
  walk(node);
  return parts.join("").replace(/\s+/g, " ").trim();
}

/** Every match for a selector, at any shadow depth. */
export function deepQuery<T extends Element = Element>(node: Node, selector: string): T[] {
  const found: T[] = [];
  const walk = (current: Node): void => {
    if (current.nodeType === 1) {
      const element = current as Element;
      if (element.matches?.(selector)) found.push(element as unknown as T);
      if (element.shadowRoot) walk(element.shadowRoot);
    }
    current.childNodes.forEach(walk);
  };
  walk(node);
  return found;
}

/** Let every element in the tree finish rendering, however deep. */
export async function settle(root: Element): Promise<void> {
  for (let pass = 0; pass < 4; pass += 1) {
    await new Promise((resolve) => setTimeout(resolve, 0));
    for (const element of deepQuery<Element & { updateComplete?: Promise<unknown> }>(root, "*")) {
      if (element.updateComplete) await element.updateComplete;
    }
  }
}

/** The button whose visible text is exactly this. */
export function button(root: Element, label: string): HTMLButtonElement {
  const match = deepQuery<HTMLButtonElement>(root, "button").find(
    (candidate) => (candidate.textContent ?? "").trim() === label,
  );
  if (!match) {
    const seen = deepQuery<HTMLButtonElement>(root, "button")
      .map((candidate) => `"${(candidate.textContent ?? "").trim()}"`)
      .join(", ");
    throw new Error(`no button labelled "${label}". Present: ${seen}`);
  }
  return match;
}
