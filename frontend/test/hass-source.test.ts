/**
 * The real source, against a Home Assistant made of three fields.
 *
 * What is worth pinning here is the plumbing that has no other check: writes go
 * to services and nowhere else, the cursor is read off the entity rather than
 * guessed, and a fresh `hass` for a light in the hall does not make this
 * re-fetch a dish.
 */

import { describe, expect, it, vi } from "vitest";
import { HassCookAlongSource, type Hass, type HassEntity } from "../src/hass-source.js";
import { cake, library } from "./support.js";

function entity(state: string, attributes: Record<string, unknown> = {}): HassEntity {
  return { entity_id: "sensor.x", state, attributes };
}

function hassWith(states: Record<string, HassEntity>): Hass & {
  callService: ReturnType<typeof vi.fn>;
  callApi: ReturnType<typeof vi.fn>;
} {
  return {
    states,
    callService: vi.fn(async () => undefined),
    callApi: vi.fn(async (_method: string, path: string) =>
      path.startsWith("recipe_wizard/library") ? library : cake,
    ),
  } as never;
}

const COOKING = {
  "sensor.recipe_wizard_current_step": entity("4/21", {
    dish_id: cake.id,
    dish: cake.name,
    batches: 2,
    step_number: 4,
    of: 21,
    recipe_id: cake.id,
    step_id: "#beat-to-ribbon",
    attention: "passive",
  }),
  "sensor.recipe_wizard_step_timer": entity("2026-08-19T18:00:00+00:00", {}),
};

describe("the cursor, read off the entity", () => {
  it("is idle when there is no cook-along, which is not a broken sensor", () => {
    const source = new HassCookAlongSource();
    source.update(hassWith({ "sensor.recipe_wizard_current_step": entity("idle") }));
    expect(source.cursor()).toEqual({ status: "idle", awaitingCheck: false });
  });

  it("carries the position, the pair, and when the estimate runs out", () => {
    const source = new HassCookAlongSource();
    source.update(hassWith(COOKING));
    const cursor = source.cursor();
    expect(cursor.status).toBe("cooking");
    expect(cursor.position).toBe(4);
    expect(cursor.of).toBe(21);
    expect(cursor.batches).toBe(2);
    expect(cursor.stepId).toBe("#beat-to-ribbon");
    expect(cursor.stepRecipeId).toBe(cake.id);
    expect(cursor.estimateEndsAt).toBe(Date.parse("2026-08-19T18:00:00+00:00"));
  });

  it("passes on the awaiting-check flag the integration published", () => {
    const source = new HassCookAlongSource();
    const states = {
      ...COOKING,
      "sensor.recipe_wizard_current_step": entity("4/21", {
        ...COOKING["sensor.recipe_wizard_current_step"].attributes,
        awaiting_check: true,
      }),
    };
    source.update(hassWith(states));
    expect(source.cursor().awaitingCheck).toBe(true);
  });

  it("reports a recipe that will not resolve as unknown, with the reason", () => {
    const source = new HassCookAlongSource();
    source.update(
      hassWith({
        "sensor.recipe_wizard_current_step": entity("unknown", {
          dish_id: cake.id,
          recipe_id: cake.id,
          batches: 1,
          problem: "no such recipe: pavlova",
        }),
      }),
    );
    const cursor = source.cursor();
    expect(cursor.status).toBe("unknown");
    expect(cursor.problem).toContain("pavlova");
    expect(cursor.recipeId).toBe(cake.id);
  });

  it("knows the dish even when the cook is inside a component of it", () => {
    // The entity's `recipe_id` is the *step's* recipe, which is the buttercream
    // once the cook is frosting the cake. `dish_id` is the dish's own, and the
    // two are read from different attributes rather than one being guessed from
    // the other -- this used to match the `dish` label against recipe names,
    // which a reload, a rename or two recipes sharing a name all defeated.
    const source = new HassCookAlongSource();
    source.update(
      hassWith({
        "sensor.recipe_wizard_current_step": entity("20/21", {
          dish_id: cake.id,
          dish: cake.name,
          batches: 2,
          recipe_id: "urn:recipe:rte/vanilla-buttercream",
          step_id: "#whip",
        }),
      }),
    );
    // No `library()` call: the dish is known from the entity alone, which is
    // what makes a freshly opened panel work before it has fetched anything.
    expect(source.cursor().recipeId).toBe(cake.id);
    expect(source.cursor().stepRecipeId).toBe("urn:recipe:rte/vanilla-buttercream");
  });
});

describe("the movements", () => {
  it("go through services, with the parameters the integration declares", async () => {
    const source = new HassCookAlongSource();
    const hass = hassWith(COOKING);
    source.update(hass);

    await source.start(cake.id, 2);
    await source.next();
    await source.previous();
    await source.stop();

    expect(hass.callService.mock.calls).toEqual([
      ["recipe_wizard", "start_cook_along", { recipe_id: cake.id, batches: 2 }],
      ["recipe_wizard", "next_step", undefined],
      ["recipe_wizard", "previous_step", undefined],
      ["recipe_wizard", "stop_cook_along", undefined],
    ]);
  });
});

describe("the dish", () => {
  it("is fetched over HTTP, at the scale being cooked", async () => {
    const source = new HassCookAlongSource();
    const hass = hassWith(COOKING);
    source.update(hass);

    await source.dish(cake.id, 2);
    const [method, path] = hass.callApi.mock.calls.at(-1)!;
    expect(method).toBe("GET");
    expect(path).toContain("recipe_wizard/dish/");
    expect(path).toContain("batches=2");
    expect(path).toContain("include_optional=true");
  });
});

describe("the subscription", () => {
  it("says nothing when a light in the hall changes", () => {
    const source = new HassCookAlongSource();
    const states = { ...COOKING };
    source.update(hassWith(states));

    const listener = vi.fn();
    source.subscribe(listener);
    source.update(hassWith({ ...states }));
    expect(listener).not.toHaveBeenCalled();

    source.update(
      hassWith({ ...states, "sensor.recipe_wizard_current_step": entity("5/21", {}) }),
    );
    expect(listener).toHaveBeenCalledOnce();
  });
});
