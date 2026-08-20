/**
 * The clock port, and what the surface is allowed to claim about a number.
 *
 * Every assertion here would otherwise be a wait: the whole reason `now()` is a
 * port is that "the estimate runs out" should be a line in a test rather than
 * seven real minutes.
 */

import { describe, expect, it } from "vitest";
import { ManualClock } from "../src/clock.js";
import { countdown, formatRemaining, nextTick } from "../src/countdown.js";
import type { CursorState } from "../src/ports.js";
import type { Step } from "../src/payload.js";
import { cake } from "./support.js";

const stateStep = cake.steps.find((step) => step.finishes_on === "state")!;
const clockStep = cake.steps.find((step) => step.finishes_on === "clock")!;
const cookStep = cake.steps.find((step) => step.finishes_on === "cook")!;

function cursorAt(step: Step, endsAt: number | undefined): CursorState {
  return {
    status: "cooking",
    recipeId: cake.id,
    stepId: step.step_id,
    stepRecipeId: step.recipe_id,
    awaitingCheck: false,
    ...(endsAt === undefined ? {} : { estimateEndsAt: endsAt }),
  };
}

describe("the countdown", () => {
  it("is the difference between when the estimate ends and what time it is", () => {
    const state = countdown(stateStep, cursorAt(stateStep, 10_000), 4_000);
    expect(state.remainingMs).toBe(6_000);
    expect(state.passed).toBe(false);
    expect(state.awaitingCheck).toBe(false);
  });

  it("turns into a question, not a zero, on a step the food decides", () => {
    const state = countdown(stateStep, cursorAt(stateStep, 10_000), 10_001);
    expect(state.passed).toBe(true);
    expect(state.awaitingCheck).toBe(true);
  });

  it("does not call a step awaiting-check when the clock is the instruction", () => {
    // "Beat the eggs for 30 seconds" is not estimating anything. Hedging it
    // teaches a cook to discount every number on the screen.
    const state = countdown(clockStep, cursorAt(clockStep, 10_000), 99_000);
    expect(state.passed).toBe(true);
    expect(state.awaitingCheck).toBe(false);
  });

  it("takes the source's word for it even when it has no end time to check", () => {
    const cursor = { ...cursorAt(cookStep, undefined), awaitingCheck: true };
    const state = countdown(cookStep, cursor, 0);
    expect(state.remainingMs).toBeNull();
    expect(state.awaitingCheck).toBe(true);
  });

  it("counts nothing where the document supports no arithmetic", () => {
    const state = countdown(cookStep, cursorAt(cookStep, undefined), 0);
    expect(state.remainingMs).toBeNull();
    expect(state.passed).toBe(false);
  });
});

describe("formatting what is left", () => {
  it("reads as a clock, with hours only when there are some", () => {
    expect(formatRemaining(0)).toBe("0:00");
    expect(formatRemaining(1_000)).toBe("0:01");
    expect(formatRemaining(61_000)).toBe("1:01");
    expect(formatRemaining(3_600_000)).toBe("1:00:00");
    expect(formatRemaining(-5_000)).toBe("0:00");
  });

  it("rounds up, so a second is on the screen for the whole of it", () => {
    expect(formatRemaining(1_500)).toBe("0:02");
  });
});

describe("waking up", () => {
  it("asks for the next whole second and not a ticker", () => {
    expect(nextTick(5_400, 1_000)).toBe(1_400);
    expect(nextTick(5_000, 1_000)).toBe(2_000);
    expect(nextTick(0, 1_000)).toBeNull();
  });
});

describe("the manual clock", () => {
  it("fires what comes due, once, and cancels cleanly", () => {
    const clock = new ManualClock(0);
    let fired = 0;
    clock.schedule(1_000, () => (fired += 1));
    clock.advance(999);
    expect(fired).toBe(0);
    clock.advance(1);
    expect(fired).toBe(1);
    clock.advance(10_000);
    expect(fired).toBe(1);

    const cancel = clock.schedule(20_000, () => (fired += 1));
    cancel();
    clock.advance(20_000);
    expect(fired).toBe(1);
  });

  it("fires immediately for an instant already past", () => {
    const clock = new ManualClock(5_000);
    let fired = false;
    clock.schedule(1_000, () => (fired = true));
    expect(fired).toBe(true);
  });
});
