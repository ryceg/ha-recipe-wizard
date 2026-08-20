/**
 * The real cook-along: Home Assistant behind the port.
 *
 * Three different channels, each for the thing it is actually good at, and none
 * of them chosen twice:
 *
 * * **Writes are services.** `start_cook_along`, `next_step`, `previous_step`,
 *   `stop_cook_along`. There is no write endpoint and there must not be one: the
 *   cursor lives in the config entry's options, an automation moves it the same
 *   way this screen does, and a second path to it is a second place the rules
 *   about where a cook may be would have to be enforced.
 * * **The cursor is an entity.** `sensor.recipe_wizard_current_step` -- state
 *   `12/16`, `idle`, `finished`, or unknown -- and
 *   `sensor.recipe_wizard_step_timer`, a timestamp for when the current step's
 *   estimate runs out. Home Assistant pushes a fresh `hass` object on every
 *   state write, so the subscription is that push, filtered down to *these two
 *   entities changed*.
 * * **The dish is HTTP.** The entity attributes carry most of a step, but they
 *   are sized for dashboards and templates rather than as a wire format, so a
 *   cursor change is treated as an invalidation signal and the dish is fetched.
 *
 * One known rough edge, and it is a Python-side gap rather than a choice made
 * here: the cursor entity publishes the **step's** recipe id, which for a cook
 * halfway through the cake's buttercream is the buttercream and not the dish. A
 * dish must be fetched by the dish's id, so this remembers what it started and
 * otherwise matches the `dish` attribute -- a label -- against the library
 * index by name. That works and is unpleasant; a `dish_id` attribute on the
 * sensor would delete this paragraph and the method under it.
 */

import type { Dish, LibraryIndex } from "./payload.js";
import type { CookAlongSource, CursorState, Unsubscribe } from "./ports.js";

/** The slice of Home Assistant's frontend object this surface uses. */
export interface HassEntity {
  entity_id: string;
  state: string;
  attributes: Record<string, unknown>;
}

export interface Hass {
  states: Record<string, HassEntity>;
  callService(
    domain: string,
    service: string,
    data?: Record<string, unknown>,
  ): Promise<unknown>;
  /** Home Assistant's own authenticated helper, rooted at `/api/`. */
  callApi?<T>(method: string, path: string, parameters?: unknown): Promise<T>;
  fetchWithAuth?(path: string, init?: RequestInit): Promise<Response>;
}

export const CURRENT_STEP_ENTITY = "sensor.recipe_wizard_current_step";
export const STEP_TIMER_ENTITY = "sensor.recipe_wizard_step_timer";

const DOMAIN = "recipe_wizard";

export interface HassSourceOptions {
  currentStepEntity?: string;
  stepTimerEntity?: string;
}

export class HassCookAlongSource implements CookAlongSource {
  private listeners = new Set<() => void>();
  private hass: Hass | null = null;
  private lastCurrentStep: HassEntity | undefined;
  private lastStepTimer: HassEntity | undefined;

  readonly currentStepEntity: string;
  readonly stepTimerEntity: string;

  constructor(options: HassSourceOptions = {}) {
    this.currentStepEntity = options.currentStepEntity ?? CURRENT_STEP_ENTITY;
    this.stepTimerEntity = options.stepTimerEntity ?? STEP_TIMER_ENTITY;
  }

  /**
   * Home Assistant sets `hass` on every state write in the whole system. Only a
   * change to the two entities this reads is news; anything else would re-fetch
   * a dish because a light came on.
   */
  update(hass: Hass): void {
    this.hass = hass;
    const current = hass.states[this.currentStepEntity];
    const timer = hass.states[this.stepTimerEntity];
    const changed = current !== this.lastCurrentStep || timer !== this.lastStepTimer;
    this.lastCurrentStep = current;
    this.lastStepTimer = timer;
    if (changed) this.notify();
  }

  async library(): Promise<LibraryIndex> {
    const index = await this.get<LibraryIndex>("recipe_wizard/library");
    return index;
  }

  async dish(recipeId: string, batches: number, includeOptional = true): Promise<Dish> {
    const query = new URLSearchParams({
      batches: String(batches),
      include_optional: String(includeOptional),
    });
    return this.get<Dish>(`recipe_wizard/dish/${encodeURIComponent(recipeId)}?${query}`);
  }

  cursor(): CursorState {
    const entity = this.hass?.states[this.currentStepEntity];
    if (!entity || entity.state === "unavailable") return { status: "idle", awaitingCheck: false };

    const attributes = entity.attributes;
    const batches = numberOr(attributes["batches"], undefined);
    const problem = stringOr(attributes["problem"]);
    if (problem !== undefined || entity.state === "unknown" || entity.state === "") {
      return {
        status: "unknown",
        recipeId: this.dishId(attributes),
        batches,
        awaitingCheck: false,
        problem: problem ?? "The cook-along is not answering.",
      };
    }
    if (entity.state === "idle") return { status: "idle", awaitingCheck: false };
    if (entity.state === "finished") {
      return {
        status: "finished",
        recipeId: this.dishId(attributes),
        batches,
        of: numberOr(attributes["of"], undefined),
        awaitingCheck: false,
      };
    }

    const [position, of] = entity.state.split("/").map((part) => Number(part));
    const ends = this.estimateEndsAt();
    return {
      status: "cooking",
      recipeId: this.dishId(attributes),
      batches,
      stepId: stringOr(attributes["step_id"]),
      stepRecipeId: stringOr(attributes["recipe_id"]),
      position: Number.isFinite(position) ? position : numberOr(attributes["step_number"], undefined),
      of: Number.isFinite(of) ? of : numberOr(attributes["of"], undefined),
      ...(ends === undefined ? {} : { estimateEndsAt: ends }),
      awaitingCheck: attributes["awaiting_check"] === true || this.timerAttribute("awaiting_check") === true,
    };
  }

  subscribe(listener: () => void): Unsubscribe {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  async start(recipeId: string, batches: number): Promise<void> {
    await this.call("start_cook_along", { recipe_id: recipeId, batches });
  }

  async next(): Promise<void> {
    await this.call("next_step");
  }

  async previous(): Promise<void> {
    await this.call("previous_step");
  }

  async stop(): Promise<void> {
    await this.call("stop_cook_along");
  }

  // -- the three channels ---------------------------------------------------

  private async call(service: string, data?: Record<string, unknown>): Promise<void> {
    if (!this.hass) throw new Error("Home Assistant is not connected yet.");
    await this.hass.callService(DOMAIN, service, data);
  }

  /**
   * `hass.callApi` first: it is Home Assistant's own helper and carries the
   * auth. `fetchWithAuth` next, for a frontend old enough not to have it. Plain
   * `fetch` last, which only works where a session cookie does -- kept because a
   * dev server pointing at a real instance is worth the two lines.
   */
  private async get<T>(path: string): Promise<T> {
    const hass = this.hass;
    if (!hass) throw new Error("Home Assistant is not connected yet.");
    if (hass.callApi) return hass.callApi<T>("GET", path);
    const response = hass.fetchWithAuth
      ? await hass.fetchWithAuth(`/api/${path}`)
      : await fetch(`/api/${path}`);
    if (!response.ok) throw new Error(`${response.status} from /api/${path}`);
    return (await response.json()) as T;
  }

  /** When the current step's estimate runs out, from the timestamp entity that
   * already decides when it is honest to answer at all. */
  private estimateEndsAt(): number | undefined {
    const entity = this.hass?.states[this.stepTimerEntity];
    if (!entity) return undefined;
    const at = Date.parse(entity.state);
    return Number.isFinite(at) ? at : undefined;
  }

  private timerAttribute(name: string): unknown {
    return this.hass?.states[this.stepTimerEntity]?.attributes[name];
  }

  /**
   * Which dish is being cooked -- which is not what the cursor entity's
   * `recipe_id` attribute says once the cook is inside a component.
   *
   * In order: what this surface itself started, the `dish` label matched against
   * the library index, and finally the step's recipe, which is right whenever
   * the cook is in the dish's own steps and is the best guess otherwise.
   */
  /**
   * The **dish's** recipe, straight off the sensor.
   *
   * `recipe_id` is the *step's* recipe and is a different document once the cook
   * is frosting the cake, so it is not the thing to fetch a dish with. This used
   * to remember what this surface had started and otherwise match the `dish`
   * label against recipe names -- which broke on a page reload, on two recipes
   * sharing a name, and on a rename, and fell back to fetching the buttercream.
   * `dish_id` exists so that guessing is not necessary.
   */
  private dishId(attributes: Record<string, unknown>): string | undefined {
    return stringOr(attributes["dish_id"]);
  }

  private notify(): void {
    for (const listener of [...this.listeners]) listener();
  }
}

function stringOr(value: unknown): string | undefined {
  return typeof value === "string" && value !== "" ? value : undefined;
}

function numberOr(value: unknown, fallback: number | undefined): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}
