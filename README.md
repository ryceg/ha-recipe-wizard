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
python -m recipe_wizard --list --validate
python -m pytest
```

No dependencies beyond the standard library; `pytest` only for the tests.

## Adding a recipe

```bash
python -m recipe_wizard --import <URL> > recipes/<slug>.json   # faithful level 0
# enrich it -- see .claude/skills/enrich-recipe/SKILL.md
python -m recipe_wizard <slug> --validate                      # iterate to zero errors
python -m recipe_wizard <slug> --plan                          # catches what the validator can't
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
| `custom_components/recipe_wizard/core/` | The core library. No Home Assistant dependency, on purpose |
| `custom_components/recipe_wizard/data/foods.json` | Food concepts, densities and per-unit masses |
| `recipes/` | Seven worked recipes, encoding the real sources faithfully |
| `tests/` | 117 tests, most of them named after a failure mode |

Core modules: `resolve.py` (the pipeline), `dish.py` (a recipe resolved together
with its components), `schedule.py` (constraint solving), `adjust.py` (patch
operations), `mass.py` (unit reconciliation), `render.py` (the table and the
cook-along view), `validate.py`.

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

Things were also **cut** after turning out to serve requirements nobody had:
coverage geometry (~300 lines that converted "enough for a 20 cm cake" into
grams), family-based component swapping, OR nodes, tool occupancy, and recipe
parameters — no recipe ever declared one, so that resolver step ran on an empty
list for every recipe in the bank. The reasoning for each is in the format doc.

Full reasoning in [`docs/format.md`](docs/format.md).

## Next

* Home Assistant integration wrapping this library — entities per recipe, step
  timers, and the cook-along view that `ingredients_for_step()` already backs.
* Enrichment skills lifting scraped recipes from level 0 to level 3, iterating
  against the validator until it is clean.
* The gaps listed at the end of the format doc — doneness driving timers,
  conditional steps, shopping-list roll-up.

Recipe content in `recipes/` is transcribed from the sources linked in each
file for personal use, with attribution retained in `author` and `isBasedOn`.
