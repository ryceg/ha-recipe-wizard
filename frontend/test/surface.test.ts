/**
 * The fixture source drives the surface, end to end, with no Home Assistant and
 * no real time passing.
 */

import { describe, expect, it } from "vitest";
import "../src/elements/surface.js";
import type { RecipeWizardSurface } from "../src/elements/surface.js";
import { button, cake, deepQuery, fixtureSource, settle, shadowText } from "./support.js";

async function mount(): Promise<{
  surface: RecipeWizardSurface;
  clock: ReturnType<typeof fixtureSource>["clock"];
}> {
  const { source, clock } = fixtureSource();
  const surface = document.createElement("recipe-wizard-surface");
  surface.source = source;
  surface.clock = clock;
  document.body.replaceChildren(surface);
  await settle(surface);
  return { surface, clock };
}

async function startCooking(): Promise<Awaited<ReturnType<typeof mount>>> {
  const mounted = await mount();
  button(mounted.surface, cake.name).click();
  await settle(mounted.surface);
  button(mounted.surface, "Start cooking").click();
  await settle(mounted.surface);
  return mounted;
}

describe("the surface, on the fixture source", () => {
  it("offers every recipe in the library as something to cook", async () => {
    const { surface } = await mount();
    const labels = deepQuery<HTMLButtonElement>(surface, "button").map((element) =>
      (element.textContent ?? "").trim(),
    );
    expect(labels).toContain("My Very Best Vanilla Cake");
    expect(labels).toContain("Vanilla Buttercream");
  });

  it("puts the cook on the first step of the dish they picked", async () => {
    const { surface } = await startCooking();
    const text = shadowText(surface);
    expect(text).toContain(cake.steps[0]!.text);
    expect(text).toContain(`1/${cake.steps.length}`);
  });

  it("moves the cook forwards and back, one step at a time", async () => {
    const { surface } = await startCooking();

    button(surface, "Next").click();
    await settle(surface);
    expect(shadowText(surface)).toContain(cake.steps[1]!.text);

    button(surface, "Back").click();
    await settle(surface);
    expect(shadowText(surface)).toContain(cake.steps[0]!.text);
  });

  it("renders what a step needs in the library's own words, at this batch size", async () => {
    const { surface } = await startCooking();
    button(surface, "Next").click();
    await settle(surface);

    // "420 g large eggs" -- scaled by the resolver, phrased by the library, and
    // never reassembled out of the parts beside it.
    const needed = cake.steps[1]!.needs[0]!;
    expect(needed.text).toBeTruthy();
    expect(shadowText(surface)).toContain(needed.text);
  });

  it("keeps the cook's position when the library says where they are", async () => {
    const { surface } = await startCooking();
    button(surface, "Next").click();
    await settle(surface);
    expect(shadowText(surface)).toContain(`2/${cake.steps.length}`);
  });

  it("stops counting and starts asking when a state-decided estimate runs out", async () => {
    const { surface, clock } = await startCooking();
    // Three taps to #beat-to-ribbon: "Beat for 7 minutes until tripled in volume
    // and white/pale" -- seven minutes is an estimate of a state, not a promise.
    for (let tap = 0; tap < 3; tap += 1) {
      button(surface, "Next").click();
      await settle(surface);
    }
    const step = cake.steps[3]!;
    expect(step.finishes_on).toBe("state");
    expect(shadowText(surface)).toContain(step.doneness!);

    clock.advance(step.timer_s! * 1000 + 1);
    await settle(surface);

    const text = shadowText(surface);
    expect(text).toContain("Check now");
    expect(text).toContain(step.doneness!);
    expect(text).not.toContain("0:00");
  });

  it("shows the resolver's warnings rather than hiding or refusing them", async () => {
    const { surface } = await startCooking();
    // The doubled cake will not fit the tins the recipe names. Nothing is wrong
    // with the document; the cook is the one who needs to know.
    expect(cake.findings.length).toBeGreaterThan(0);
    expect(shadowText(surface)).toContain(cake.findings[0]!.message);
  });

  it("goes back to the library when the cook stops", async () => {
    const { surface } = await startCooking();
    button(surface, "Stop").click();
    await settle(surface);
    expect(shadowText(surface)).toContain("What are we cooking?");
  });
});
