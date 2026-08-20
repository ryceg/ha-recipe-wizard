/**
 * What a step looks like, and the four things about it a screen can quietly
 * undo.
 *
 * The element is rendered on its own here, handed a step and a countdown, so
 * these are assertions about what is drawn and not about when.
 */

import { describe, expect, it } from "vitest";
import "../src/elements/step.js";
import type { RecipeWizardStep } from "../src/elements/step.js";
import type { Countdown } from "../src/countdown.js";
import type { Step } from "../src/payload.js";
import { cake, settle, shadowText } from "./support.js";

const NOT_STARTED: Countdown = { remainingMs: null, passed: false, awaitingCheck: false };

async function render(step: Step, count: Countdown = NOT_STARTED): Promise<RecipeWizardStep> {
  const element = document.createElement("recipe-wizard-step") as RecipeWizardStep;
  element.dish = cake;
  element.step = step;
  element.countdown = count;
  element.position = step.cursor + 1;
  element.of = step.of;
  document.body.replaceChildren(element);
  await settle(element);
  return element;
}

const stateStep = cake.steps.find((step) => step.finishes_on === "state" && !!step.doneness)!;
const clockStep = cake.steps.find((step) => step.finishes_on === "clock" && !!step.timer)!;
const cookStep = cake.steps.find((step) => step.finishes_on === "cook")!;

describe("a step the food decides", () => {
  it("shows the doneness while it is still counting", async () => {
    const element = await render(stateStep, {
      remainingMs: 90_000,
      passed: false,
      awaitingCheck: false,
    });
    const text = shadowText(element);
    expect(text).toContain(stateStep.doneness!);
    expect(text).toContain("1:30");
    // The number is present, and labelled as what it is.
    expect(text).toContain("estimated");
  });

  it("stops counting and starts asking once the estimate has run out", async () => {
    const element = await render(stateStep, {
      remainingMs: -1,
      passed: true,
      awaitingCheck: true,
    });
    const text = shadowText(element);
    expect(text).toContain("Check now");
    expect(text).toContain(stateStep.doneness!);
    expect(text).not.toContain("0:00");
    expect(text).not.toContain("estimated");
  });
});

describe("a step the clock decides", () => {
  it("states the time as the instruction and never as an estimate", async () => {
    const element = await render(clockStep, {
      remainingMs: 30_000,
      passed: false,
      awaitingCheck: false,
    });
    const text = shadowText(element);
    expect(text).toContain(clockStep.timer!);
    expect(text).not.toContain("estimated");
    expect(text).not.toContain("Check now");
  });
});

describe("a step the cook decides", () => {
  it("counts nothing and claims nothing", async () => {
    const element = await render(cookStep);
    const text = shadowText(element);
    expect(text).toContain("Done when you have done it");
    expect(text).not.toContain("estimated");
  });
});

describe("every step", () => {
  it("says whether the cook can walk away", async () => {
    for (const step of cake.steps.filter((entry) => entry.attention)) {
      const element = await render(step);
      expect(shadowText(element)).toContain(step.attention!);
    }
  });

  it("says where the cook is, and in which recipe of the dish", async () => {
    // A step of the buttercream inside the cake's dish reads as the
    // buttercream's -- the *use's* label, not the cake's name.
    const inComponent = cake.steps.find((step) => step.label !== cake.label);
    expect(inComponent, "the cake fixture should include its buttercream").toBeTruthy();
    const element = await render(inComponent!);
    const text = shadowText(element);
    expect(text).toContain(inComponent!.label);
    expect(text).toContain(`for ${cake.label}`);
  });
});
