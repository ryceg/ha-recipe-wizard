/**
 * A whole cook-along with no Home Assistant anywhere.
 *
 * This is not a mock of the real source, it is the second implementation of the
 * port -- the reason the port is a port. It runs the surface in a browser with
 * nothing behind it (`npm run dev`) and it runs it in the test suite, where the
 * cursor moves because a test tapped Next rather than because a service call
 * came back.
 *
 * It holds the cursor the way `cursor.py` does: by **(step recipe, step)**, with
 * the index derived rather than stored, so a fixture regenerated against a dish
 * that grew a step in a sub-recipe does not silently move the cook. The pair
 * needs both halves because a step id is unique in a recipe and not in a dish --
 * the cake and its buttercream both have an `#add-sugar`. And like `cursor.py`
 * it arms a wake-up on the clock at the instant a state-finished step's estimate
 * runs out, so *awaiting check* arrives as an event rather than as something the
 * screen happens to notice.
 */

import type { Dish, Step, LibraryIndex } from "./payload.js";
import type { Clock, CookAlongSource, CursorState, Unsubscribe } from "./ports.js";
import { SystemClock } from "./clock.js";

interface Saved {
  /** The recipe the cook asked for -- the dish, not the step's recipe. */
  dishId: string;
  batches: number;
  stepRecipeId: string;
  stepId: string;
  /** When the cook arrived at *this step*, which is the only thing that can turn
   * a stated duration into a wall-clock estimate. */
  startedAt: number;
}

export class FixtureCookAlongSource implements CookAlongSource {
  private listeners = new Set<() => void>();
  private saved: Saved | null = null;
  private finished = false;
  private awaiting = false;
  private cancelWake: Unsubscribe | null = null;

  constructor(
    private readonly index: LibraryIndex,
    /** Keyed by recipe id. Batches are ignored: a fixture is one resolution, and
     * scaling it out here would be a second resolver. */
    private readonly dishes: Record<string, Dish>,
    private readonly clock: Clock = new SystemClock(),
  ) {}

  async library(): Promise<LibraryIndex> {
    return this.index;
  }

  async dish(recipeId: string, batches: number): Promise<Dish> {
    const dish = this.dishes[recipeId];
    if (!dish) throw new Error(`no fixture for ${recipeId}`);
    return { ...dish, batches };
  }

  cursor(): CursorState {
    if (!this.saved) return { status: "idle", awaitingCheck: false };
    const dish = this.dishes[this.saved.dishId];
    if (!dish) {
      return {
        status: "unknown",
        recipeId: this.saved.dishId,
        batches: this.saved.batches,
        awaitingCheck: false,
        problem: `no fixture for ${this.saved.dishId}`,
      };
    }
    const at = this.locate(dish);
    if (this.finished || at < 0) {
      return {
        status: "finished",
        recipeId: this.saved.dishId,
        batches: this.saved.batches,
        of: dish.steps.length,
        awaitingCheck: false,
      };
    }
    const step = dish.steps[at]!;
    const ends = this.estimateEndsAt();
    return {
      status: "cooking",
      recipeId: this.saved.dishId,
      batches: this.saved.batches,
      stepId: step.step_id,
      stepRecipeId: step.recipe_id,
      position: at + 1,
      of: dish.steps.length,
      ...(ends === null ? {} : { estimateEndsAt: ends }),
      awaitingCheck: this.awaiting,
    };
  }

  subscribe(listener: () => void): Unsubscribe {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  async start(recipeId: string, batches: number): Promise<void> {
    // A family is a browsing tag and nothing resolves through one. The real
    // resolver refuses an id that is not a recipe, and so does this: a picker
    // that offered `family:buttercream` would fail here rather than on the wire.
    const known = this.index.recipes.some((recipe) => recipe.id === recipeId);
    if (!known) throw new Error(`not a recipe: ${recipeId}`);
    const dish = this.dishes[recipeId];
    if (!dish || dish.steps.length === 0) throw new Error(`nothing to cook in ${recipeId}`);
    this.finished = false;
    this.arrive(recipeId, batches, dish.steps[0]!);
  }

  async next(): Promise<void> {
    this.move(+1);
  }

  async previous(): Promise<void> {
    this.move(-1);
  }

  async stop(): Promise<void> {
    this.saved = null;
    this.finished = false;
    this.disarm();
    this.notify();
  }

  // -- the cursor -----------------------------------------------------------

  /** Where the saved pair sits in this dish's walk now, or -1 if it is no longer
   * in it -- a step deleted under the cook, which reads as finished. */
  private locate(dish: Dish): number {
    const saved = this.saved;
    if (!saved) return -1;
    return dish.steps.findIndex(
      (step) => step.step_id === saved.stepId && step.recipe_id === saved.stepRecipeId,
    );
  }

  private move(by: number): void {
    if (!this.saved || this.finished) return;
    const dish = this.dishes[this.saved.dishId];
    if (!dish) return;
    const at = this.locate(dish);
    if (at < 0) return;
    const to = at + by;
    if (to < 0) return;
    if (to >= dish.steps.length) {
      this.finished = true;
      this.disarm();
      this.notify();
      return;
    }
    this.arrive(this.saved.dishId, this.saved.batches, dish.steps[to]!);
  }

  private arrive(dishId: string, batches: number, step: Step): void {
    this.saved = {
      dishId,
      batches,
      stepRecipeId: step.recipe_id,
      stepId: step.step_id,
      startedAt: this.clock.now(),
    };
    this.awaiting = false;
    this.disarm();
    const ends = this.estimateEndsAt();
    if (ends !== null && step.finishes_on === "state") {
      // The estimate running out is an event of its own: the countdown reaching
      // zero is not the same thing as the food being done, and this is what lets
      // the screen stop counting and start asking.
      this.cancelWake = this.clock.schedule(ends, () => {
        this.awaiting = true;
        this.notify();
      });
    }
    this.notify();
  }

  private currentStep(): Step | undefined {
    if (!this.saved) return undefined;
    const dish = this.dishes[this.saved.dishId];
    if (!dish) return undefined;
    const at = this.locate(dish);
    return at < 0 ? undefined : dish.steps[at];
  }

  /** Only where the document supports the arithmetic: a stated duration, and a
   * timer that starts on arriving at the step rather than on something at the
   * bench that nothing here can see. */
  private estimateEndsAt(): number | null {
    const step = this.currentStep();
    if (!this.saved || !step) return null;
    if (step.timer_s === undefined || step.timer_starts_when !== undefined) return null;
    return this.saved.startedAt + step.timer_s * 1000;
  }

  private disarm(): void {
    this.cancelWake?.();
    this.cancelWake = null;
  }

  private notify(): void {
    for (const listener of [...this.listeners]) listener();
  }
}
