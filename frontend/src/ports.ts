/**
 * The two ports the surface is written against, so it does not know where it is
 * mounted or what time it is.
 *
 * **CookAlongSource** is where a cook-along lives: what there is to cook, the
 * dish at a scale, where the cook is, and the four movements. There are two
 * implementations and both are load-bearing. `HassCookAlongSource` is the real
 * one -- services for the writes, `hass.states` for the cursor, `fetch` for the
 * dish. `FixtureCookAlongSource` is the whole surface with no Home Assistant
 * anywhere, which is what makes the tests and local development possible; a port
 * with one implementation is a layer of indirection, and this one has two.
 *
 * **Clock** exists so the countdown is deterministic under test. The split is
 * the point: the *source* says when a step's estimate runs out, the *clock* says
 * what time it is now, and the surface renders the difference. It is not an
 * extension point for notifications, speakers or wake-ups -- Home Assistant does
 * that already, from automations on `sensor.recipe_wizard_step_timer`.
 */

import type { Dish, LibraryIndex } from "./payload.js";

/**
 * Where the cook is, flattened out of whatever the implementation reads it from.
 *
 * Deliberately small. The cursor entity's attributes carry most of a step, but
 * they are sized for dashboards and templates rather than as a wire format, so
 * the surface treats a change to them as an *invalidation signal* and re-fetches
 * the dish. What this carries is only what the dish cannot say: which recipe,
 * which step, and the two things that are true of this cook rather than of the
 * document -- when the estimate runs out, and whether it already has.
 */
export interface CursorState {
  /**
   * `idle` -- no cook-along on the go. `cooking` -- somewhere in one.
   * `finished` -- past the last step. `unknown` -- running, but the recipe
   * cannot be resolved right now, so nothing knows where the cook is.
   */
  status: "idle" | "cooking" | "finished" | "unknown";
  recipeId?: string;
  batches?: number;
  /**
   * A cursor is (recipe, step), never an index (ADR 0003): the walk is the
   * dish's steps then each component's, so a step added to a *sub-recipe*
   * renumbers the parent and an index silently moves the cook.
   */
  stepId?: string;
  /** Which recipe in the dish that step belongs to -- the other half of the
   * pair, and not the same as `recipeId`: the cook may be on the buttercream's
   * second step, inside the cake's dish. */
  stepRecipeId?: string;
  /** The cook's position, 1-based, as the sensor's state reads it: `12/16`. */
  position?: number;
  of?: number;
  /**
   * When the current step's stated time runs out, as epoch milliseconds --
   * absent wherever the document does not support the arithmetic. Never a
   * promise that the step ends then: on a step a *state* finishes it is an
   * estimate of it, and the doneness is what decides.
   */
  estimateEndsAt?: number;
  /** The estimate has run out and the step is not over. */
  awaitingCheck: boolean;
  /** Running, but the recipe will not resolve. The cook is somewhere in it. */
  problem?: string;
}

export const IDLE: CursorState = { status: "idle", awaitingCheck: false };

/** Told when the cursor moved, or the dish under it was re-resolved. */
export type Unsubscribe = () => void;

export interface CookAlongSource {
  /** What there is to cook, and what merely groups it. */
  library(): Promise<LibraryIndex>;

  /** One recipe resolved at one scale, with its components expanded. */
  dish(recipeId: string, batches: number, includeOptional?: boolean): Promise<Dish>;

  /** Where the cook is, as of the last thing this source heard. Synchronous:
   * the surface renders from it and must not await in a render. */
  cursor(): CursorState;

  subscribe(listener: () => void): Unsubscribe;

  /** The four movements. Writes go through Home Assistant services in the real
   * implementation; there is no write endpoint. */
  start(recipeId: string, batches: number): Promise<void>;
  next(): Promise<void>;
  previous(): Promise<void>;
  stop(): Promise<void>;
}

export interface Clock {
  /** Epoch milliseconds. */
  now(): number;
  /**
   * Call `fn` when `at` arrives (or immediately, if it has passed). Returns the
   * cancel. One wake-up per scheduled instant -- the surface asks for the next
   * whole second it needs, rather than being handed a ticker it has to throttle.
   */
  schedule(at: number, fn: () => void): Unsubscribe;
}
