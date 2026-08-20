/**
 * The shapes `core/serialise.py` writes, as TypeScript.
 *
 * These are read-only mirrors of that module and nothing more. **This is not the
 * format** -- `docs/format.md` describes what is on disk; what arrives here is a
 * *dish*: one recipe resolved at one scale with its components expanded, derived
 * and disposable. `serialise.py` says the shape is private, carries no version
 * and may change in any release, which is exactly why it is transcribed in one
 * file here rather than assumed field-by-field across the surface.
 *
 * Every optional field is optional because `_clean()` drops keys whose value is
 * `None`. `false` and `0` are *not* dropped: "the cook may not pause here" and
 * "no pause information" are different claims and the payload keeps them apart.
 *
 * Two rules the rest of this directory depends on:
 *
 * * durations are **seconds as numbers**, never ISO strings;
 * * anything a cook reads as a sentence already has a `text` (or `timer`) field
 *   the library wrote. Reassembling one from the parts here would be a second
 *   place that phrasing lives, and the two would drift.
 */

/** Whether the cook can walk away. */
export type Attention = "active" | "passive" | "unattended";

/**
 * What ends a step. A `state` means the food decides and any stated time is an
 * estimate of it; the `clock` means the time *is* the instruction; the `cook`
 * means it is done when they have done it. One property, because every surface
 * used to decide this privately and they disagreed.
 */
export type FinishesOn = "state" | "clock" | "cook";

export interface Portion {
  /** Display-only, and never resolved to a mass. */
  text: string;
  whole: boolean;
  approximate?: boolean;
}

export interface RequiredState {
  description: string;
  lead_time_s?: number;
  procedure?: string;
}

/** One thing the cook needs in front of them, at this batch size. */
export interface Needed {
  id: string;
  name: string;
  /** The library's sentence: "4 tbsp smooth peanut butter (of 500 g)". */
  text: string;
  portion: Portion;
  row_mass_g?: number;
  optional: boolean;
  to_taste: boolean;
  display?: string;
  note?: string;
  required_state?: RequiredState;
}

export interface Product {
  id: string;
  name?: string;
}

/** One position in the walk: what to do, with what, and what ends it. */
export interface Step {
  /** The dish-wide index of this position. Not a saved cursor -- see ADR 0003. */
  cursor: number;
  of: number;
  /** With `step_id`, the pair that identifies a step: the cake and its
   * buttercream both have an `#add-sugar`. */
  recipe_id: string;
  /** The *use's* label, so the cake's frosting reads "Vanilla buttercream". */
  label: string;
  step_id: string;
  position: number;
  text: string;
  attention?: Attention;
  start_s?: number;
  end_s?: number;
  timer_s?: number;
  timer_max_s?: number;
  /** "32 min, then check: edges firmish, centre still jiggling" -- written once,
   * by the library, and never rebuilt out here. */
  timer?: string;
  doneness?: string;
  finishes_on: FinishesOn;
  time_is_estimate?: boolean;
  timer_starts_when?: string;
  safety_note?: string;
  may_pause_after?: boolean;
  needs: Needed[];
  produces: Product[];
}

export interface Finding {
  level: string;
  code: string;
  recipe: string;
  node?: string;
  message: string;
  /** The *use's* label, the only thing that says which use a finding belongs to
   * when one sub-recipe is used twice. */
  where?: string;
}

export interface Storage {
  method: string;
  keeps?: string;
  keeps_s?: number;
  quality_window?: string;
  quality_note?: string;
  condition?: string;
  note?: string;
}

/** A parent's use of a sub-recipe -- never the sub-recipe itself. */
export interface ComponentUse {
  label: string;
  recipe_id: string;
  batches: number;
  summary: string;
  produced_g?: number;
  requested_g?: number;
  optional: boolean;
  change_log: string[];
}

/**
 * The Modernist table, the plan and the shopping list ride along in every dish
 * payload. The first cut of this surface renders none of them; they are typed
 * as opaque so that adding a section later is a rendering change and not a
 * change to what is fetched.
 */
export interface Dish {
  id: string;
  name: string;
  label: string;
  url?: string;
  batches: number;
  yield_g?: number;
  yield_basis?: string;
  produced_g?: number;
  storage: Storage[];
  unsuitable_for: string[];
  notes: string[];
  table: unknown[];
  steps: Step[];
  plan: unknown;
  shopping: unknown;
  components: ComponentUse[];
  findings: Finding[];
}

export interface RecipeSummary {
  id: string;
  name: string;
  url?: string;
  variant_of?: string;
  family?: string;
  enrichment_level: number;
}

/**
 * A browsing tag grouping siblings. **Nothing resolves through a family** -- it
 * is not a thing to cook, and a picker that offered `family:buttercream` as a
 * choosable row would be offering something no resolver accepts.
 */
export interface Family {
  id: string;
  name: string;
  members: string[];
}

export interface LibraryIndex {
  recipes: RecipeSummary[];
  families: Family[];
}
