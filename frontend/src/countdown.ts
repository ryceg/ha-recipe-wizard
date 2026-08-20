/**
 * The difference between when a step's estimate runs out and what time it is.
 *
 * A pure function of the step, the cursor and an instant, so that "the estimate
 * runs out and the screen stops counting and starts asking" is a unit test and
 * not a wait.
 *
 * The one judgement in here is `awaitingCheck`. The source reports it too --
 * `cursor.py` arms a wake-up and the sensor publishes the flag -- and this
 * *also* derives it from the clock rather than only trusting the flag, because
 * the two answer at different moments: the entity updates when Home Assistant
 * gets round to writing the state, and the cook is looking at the screen at the
 * instant the number reaches zero. Either one is enough to flip it; neither can
 * un-flip the other.
 *
 * What is deliberately *not* here is any hedging of a `clock` step. "Beat the
 * eggs for 30 seconds" is not an estimate of anything, and a surface that
 * qualifies its certain numbers has no way left to mark its uncertain ones.
 */

import type { Step } from "./payload.js";
import type { CursorState } from "./ports.js";

export interface Countdown {
  /** Milliseconds until the estimate runs out; negative once it has passed.
   * `null` where the document does not support the arithmetic at all. */
  remainingMs: number | null;
  /** The estimate has run out. Says nothing about whether the step is over. */
  passed: boolean;
  /**
   * The estimate has run out on a step whose **state** decides. The countdown
   * reaching zero and the food being done are not the same event, and this is
   * the one that means: stop counting, start asking.
   */
  awaitingCheck: boolean;
}

export function countdown(step: Step, cursor: CursorState, now: number): Countdown {
  const ends = cursor.estimateEndsAt;
  if (ends === undefined) {
    return { remainingMs: null, passed: false, awaitingCheck: cursor.awaitingCheck };
  }
  const remainingMs = ends - now;
  const passed = remainingMs <= 0;
  return {
    remainingMs,
    passed,
    awaitingCheck: cursor.awaitingCheck || (passed && step.finishes_on === "state"),
  };
}

/**
 * A running clock, as `1:02:33` or `4:07`.
 *
 * Not a violation of "never rebuild a sentence the library wrote": the library
 * writes what the *document* says -- "32 min, then check: edges firmish" -- and
 * that string is rendered verbatim beside this one. This is how long is left,
 * which nothing on the Python side can know, because only this screen knows what
 * time it is now.
 */
export function formatRemaining(ms: number): string {
  const total = Math.max(0, Math.ceil(ms / 1000));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;
  const pad = (value: number) => String(value).padStart(2, "0");
  return hours > 0 ? `${hours}:${pad(minutes)}:${pad(seconds)}` : `${minutes}:${pad(seconds)}`;
}

/**
 * When the surface next needs to redraw: the next whole second of the countdown,
 * or the instant it runs out. One wake-up at a time rather than a ticker, so a
 * screen showing a three-hour chill is not repainting sixty times a minute.
 */
export function nextTick(remainingMs: number, now: number): number | null {
  if (remainingMs <= 0) return null;
  const sinceLastWholeSecond = remainingMs % 1000;
  return now + (sinceLastWholeSecond === 0 ? 1000 : sinceLastWholeSecond);
}
