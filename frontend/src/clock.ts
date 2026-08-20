/**
 * What time it is, and one wake-up at a time.
 *
 * `SystemClock` is the whole production implementation and is four lines,
 * which is the argument for the port: the alternative is `Date.now()` and
 * `setTimeout` sprinkled through the rendering, and a countdown test that has to
 * wait real seconds to watch an estimate run out.
 *
 * `ManualClock` is its test twin. Time only moves when a test moves it, so
 * "the estimate runs out and the screen stops counting and starts asking" is an
 * assertion rather than a race.
 */

import type { Clock, Unsubscribe } from "./ports.js";

export class SystemClock implements Clock {
  now(): number {
    return Date.now();
  }

  schedule(at: number, fn: () => void): Unsubscribe {
    // ``setTimeout`` saturates above 2^31 ms and would fire immediately on a
    // negative delay, which is right for an instant already past and wrong for
    // one three weeks out. Nothing on this surface schedules further than a
    // step's estimate, so clamping to the maximum is enough.
    const delay = Math.min(Math.max(at - this.now(), 0), 2 ** 31 - 1);
    const handle = setTimeout(fn, delay);
    return () => clearTimeout(handle);
  }
}

export class ManualClock implements Clock {
  private time: number;
  private pending: { at: number; fn: () => void }[] = [];

  constructor(start = 0) {
    this.time = start;
  }

  now(): number {
    return this.time;
  }

  schedule(at: number, fn: () => void): Unsubscribe {
    const entry = { at, fn };
    this.pending.push(entry);
    if (at <= this.time) {
      this.fire();
    }
    return () => {
      this.pending = this.pending.filter((p) => p !== entry);
    };
  }

  /** Move time forward, firing everything that comes due on the way. */
  advance(ms: number): void {
    this.time += ms;
    this.fire();
  }

  /** Move to an absolute instant. Never backwards: a clock that can go back is
   * a way to write a test that no kitchen can reproduce. */
  set(at: number): void {
    if (at < this.time) throw new Error("a clock does not run backwards");
    this.advance(at - this.time);
  }

  private fire(): void {
    const due = this.pending.filter((p) => p.at <= this.time);
    this.pending = this.pending.filter((p) => p.at > this.time);
    for (const entry of due) entry.fn();
  }
}
