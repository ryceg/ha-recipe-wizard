# ha-recipe-wizard

A structured recipe format and resolver, built to drive a Home Assistant custom
integration. Recipes are JSON-LD that stays valid schema.org, extended so they
can be **resolved** rather than only displayed: scaled to a real batch, composed
out of sub-recipes, and scheduled without ruining the food.

The presentation target is the Modernist Cuisine table — ingredients blocked
against the numbered steps that first use them — reproduced from the underlying
graph rather than authored by hand.

```
INGREDIENT                    WEIGHT  SCALING  PROCEDURE
========================================================================
plain flour                    250 g   100.0%   3. Whisk flour, baking powder,
baking powder                   11 g     4.5%      and salt in a large bowl.
kosher salt                      1 g     0.3%
                                               -> Dry mix
------------------------------------------------------------------------
large eggs                     210 g    84.0%   4. Beat eggs for 30 seconds on
                                                   speed 6 of a stand mixer.
                                               -> Beaten eggs
```

## Try it

```bash
python -m recipe_wizard --list
python -m recipe_wizard vanilla-cake --components --plan
python -m recipe_wizard vanilla-cake --batches 2 --cook       # the cook-along, doubled
python -m recipe_wizard vanilla-cake --batches 2 --shopping   # one line per food
python -m recipe_wizard --list --validate
python -m pytest
```

`--cook` is the surface everything else serves: each step in the order it is to
be done, what it needs *at this batch size*, and what its timer should say.

```
[12/16] Peanut Butter Stuffed Brownies - step 12  (active, from 130 min)
  Dollop and drizzle the reserved peanut butter across the surface, then swirl it
  with a butter knife, cutting grooves to reveal the brownie batter beneath.
    - Covered slab
    - smooth peanut butter: 4 tbsp (of 500 g)
```

`--shopping` is the second surface: one line per **food**, merged *after*
scaling and *not* on preparation, so melted butter and softened butter are one
line to buy and two things to have ready.

```
SHOPPING LIST  My Very Best Vanilla Cake  (x2)
  - plain flour: 500 g
  - unsalted butter: 680 g
      230 g, cut into cubes - My Very Best Vanilla Cake
      450 g - Vanilla buttercream
  - soft icing sugar: 1000 g
      sifted
```

A contributor with no mass — a level-0 ingredient string, or a volume whose food
the bank has no density for — never disappears into a total. The line reads
*"at least 500 g, plus 1 line with no weight"*, and `total_g` is `None`.

No dependencies beyond the standard library; `pytest` only for the tests.

## Adding a recipe

```bash
python -m recipe_wizard --import <URL> > recipes/<slug>.json   # faithful level 0
# enrich it -- see .claude/skills/enrich-recipe/SKILL.md
python -m recipe_wizard <slug> --validate                      # iterate to zero errors
python -m recipe_wizard <slug> --plan                          # read the order and the timings
```

`--validate` exits non-zero while any finding is an error, so an enrichment loop
is driven by the exit status rather than by reading the printed count. Warnings
are for a human and do not fail it. Every finding names the node a fix goes on,
so acting on one does not start by parsing the sentence:

```
[warning] urn:recipe:rte/peanut-butter-stuffed-brownies #salt-flakes: steps
account for only 50% of #salt-flakes, and no step takes the remainder
```

The importer reads the page's own schema.org JSON-LD, so no quantity is ever
paraphrased on the way in. Note that RecipeTin Eats (and most sites) strip
ingredient **section headings** from their JSON-LD, so the rendered page still
has to be read to find component boundaries.

Enrichment accuracy is measurable rather than assumed — the hand-authored
recipes are ground truth:

```bash
python -m recipe_wizard --compare candidate.json --against vanilla-cake
```

It reports precision and recall on the ingredient-to-step edges and names every
wrong and missed link.

## What's here

| Path | |
| --- | --- |
| `docs/format.md` | The format spec, and why each decision is what it is |
| `docs/integration.md` | Installing, configuring and removing the integration |
| `CONTEXT.md` | The domain language — what to call things, and what not to |
| `docs/adr/` | Decisions a future reader would otherwise undo |
| `custom_components/recipe_wizard/core/` | The core library. No Home Assistant dependency, on purpose |
| `custom_components/recipe_wizard/data/foods.json` | Food concepts, densities and per-unit masses |
| `custom_components/recipe_wizard/` | The integration itself: the config flow, the coordinator, the cook-along sensors and actions |
| `recipes/` | Seven worked recipes, encoding the real sources faithfully |
| `tests/` | 226 tests, most of them named after a failure mode |
| `tests_ha/` | The integration suite. Needs Home Assistant, so it runs on its own |

Core modules: `resolve.py` (the pipeline), `dish.py` (a recipe resolved together
with its components), `schedule.py` (constraint solving), `cookalong.py` (what to
cook now, and what its timer says), `shopping.py` (the roll-up: one line per
food), `graph.py` (the indexed dataflow graph every one of those asks),
`adjust.py` (patch operations), `mass.py` (unit reconciliation, and the one
definition of the batch total), `render.py` (the Modernist table),
`validate.py`.

Tests either build the recipe they need with `tests/support.py`, so the premise
is visible in the test, or run against the real corpus where the corpus *is* the
subject — enrichment scoring, the unit divergences, "nine findings, no errors".

The library is vendored *inside* the integration directory because HACS installs
`custom_components/recipe_wizard/` and nothing else, so anything the integration
needs at runtime has to live there — including the food bank. `recipe_wizard.py`
at the root is a three-line trampoline that keeps `python -m recipe_wizard`
working. Recipes are the exception: they are the user's data, so they sit
*beside* `custom_components/`, which is this repo root when developing and the
Home Assistant config directory once installed.

## Why it's shaped like this

The design was stress-tested against nine real recipes before and during the
build, and the data broke it repeatedly. The recipes in `recipes/` deliberately
preserve the contradictions rather than cleaning them up:

* **A step could only take all of something or none of it.** Four of six
  recipes split an ingredient — by fraction, by measure, and by remainder — so
  the table rendered the whole 250 g of peanut butter against step 2 and left
  *"dollop 2 tbsp across the surface"* with nothing. `rw:portion` fixes it, and
  the validator found a split in the cake that had been hand-written *after*
  the gap was identified.
* **Earliest-start scheduling ruins food.** It melts the cake's butter and milk
  half an hour before they go in, and mixes the brownie batter two hours early
  so it sets solid. The planner now schedules backwards from the finish, and
  independently derives the source's own *"while eggs are beating, place butter
  and milk in a jug."*
* **Chocolate buttercream is not a variant of vanilla.** Every quantity and the
  method differ. It is a *sibling* in a family — a patch would exceed the recipe.
* **The same frosting has 250 g of butter on one page and 225 g on another**,
  both called "2 sticks". Recorded as a local override, not reconciled.
* **The chocolate recipe's own two unit columns disagree by 18%.** Reported,
  never silently resolved.
* **A recipe keeps longer than it stays good.** The cake is safe for a week and
  at its best for four days; treating that as a contradiction was a bug.
* **A variant is not a document you can read off disk.** The coffee buttercream
  is a patch list — zero ingredients, zero steps — so every caller that planned
  or rendered `library.recipe(id)` showed an empty table and a 0-minute plan.
  The effective document is `Resolution.recipe`, and the two callers that used
  to take a recipe *and* a resolution (reading the weights off one and the
  procedure off the other) now take one thing, so the columns cannot disagree.

Things were also **cut** after turning out to serve requirements nobody had:
coverage geometry (~300 lines that converted "enough for a 20 cm cake" into
grams), family-based component swapping, OR nodes, tool occupancy, and recipe
parameters — no recipe ever declared one, so that resolver step ran on an empty
list for every recipe in the bank. The reasoning for each is in the format doc.

Full reasoning in [`docs/format.md`](docs/format.md).

## The integration

The cook-along is on a screen. Two sensors and four actions:
`sensor.recipe_wizard_current_step` — whose state is a position, `12/16`, because a
step's text can exceed the 255 characters a state allows and would then silently
stop updating — carries the step, what it needs at this batch size, the timer line,
the doneness, the attention and whether the cook may stop after it;
`sensor.recipe_wizard_step_timer` is a `timestamp` a dashboard renders as a
countdown, and is deliberately blank for a step that states no time or whose timer
starts on something happening at the bench. `start_cook_along`, `next_step`,
`previous_step` and `stop_cook_along` move the cursor, which lives in the config
entry's options so a restart during the brownies' three-hour chill comes back to
the chill.

Installing and configuring it is [`docs/integration.md`](docs/integration.md);
`custom_components/recipe_wizard/quality_scale.yaml` says where it stands against
the Home Assistant quality scale, exemption by exemption.

Two constraints shape all of it. `__init__.py` imports `homeassistant` inside
function bodies, because importing the library runs it first and the CLI must not
need a 300 MB dependency ([ADR 0002](docs/adr/0002-no-home-assistant-imports-at-module-scope.md),
enforced by `tests/test_packaging.py`). And every call into the library goes
through `hass.async_add_executor_job`, because `Library.load()` reads files.

The suites cannot share an interpreter — the Home Assistant test harness's autouse
fixtures attach to every test in the session and all 226 library tests error — so
there are two:

```bash
python -m pytest -q                                          # the library, bare Python

docker build -t rw-hass-test tests_ha                        # once
docker run --rm -v "$(pwd):/app" -w /app rw-hass-test \
    python -m pytest -q -o asyncio_mode=auto tests_ha        # the integration
```

The second one is a container because the harness cannot run on Windows at all
(`homeassistant.runner` imports `fcntl`), and because it needs a few requirements
the harness does not install — `tests_ha/Dockerfile` says which and why.
`-o asyncio_mode=auto` is not optional. Both suites run in CI, with `hassfest` and
HACS validation beside them.

## Next

* A `TodoListEntity` over `shopping.py`, whose lines are plain data with no
  `TodoItem` in them, hanging off the same `entry.runtime_data.coordinator`.
* Enrichment skills lifting scraped recipes from level 0 to level 3, iterating
  against the validator until it is clean.
* The gaps listed at the end of the format doc — doneness actually *holding* a
  timer rather than being displayed beside it, one timeline across component
  recipes, conditional steps, a shopping list that knows your pantry.

Recipe content in `recipes/` is transcribed from the sources linked in each
file for personal use, with attribution retained in `author` and `isBasedOn`.
