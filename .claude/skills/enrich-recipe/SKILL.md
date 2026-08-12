---
name: enrich-recipe
description: Import a recipe from a URL and enrich it to a linked, scheduleable rw JSON-LD document. Use when adding a recipe to the ha-recipe-wizard bank, lifting a scraped recipe from level 0, or when the user gives a recipe URL and asks for it in the library.
---

# Enriching a recipe

Turn a recipe page into an `rw:` document whose ingredients are linked to the
steps that use them, whose graph can be scheduled, and which passes the
validator with zero errors.

The format reference is `docs/format.md`. Read it once before your first
enrichment. `recipes/vanilla-cake.json` is the worked example to imitate.

## The loop

```bash
# 1. Import mechanically. Never hand-transcribe the strings.
python -m recipe_wizard --import <URL> > recipes/<slug>.json

# 2. Enrich the file in place (see below).

# 3. Validate. Iterate until there are zero errors: this exits non-zero while
#    any finding is an error, so the exit status is the signal.
python -m recipe_wizard <slug> --validate

# 4. Read the plan. Whether the order and the timings are what the source meant
#    is a judgement no rule makes for you.
python -m recipe_wizard <slug> --plan
```

**Stop when there are zero errors** — which is what a zero exit status from step 3
means. Warnings are for a human to read; do not silence one by inventing data. A
warning that reflects a genuine ambiguity in the source is the correct outcome.

### Reading a finding

Each one is a single line, and the field after the recipe id is the **node** to
edit:

```
[warning] urn:recipe:rte/peanut-butter-stuffed-brownies #salt-flakes: steps
account for only 50% of #salt-flakes, and no step takes the remainder
```

Go straight to that `@id` — an ingredient row, a step, or a `rw:ComponentUse` in
this document — instead of working out from the sentence which one is meant. No
node means the finding is about the whole document. The severity and the code are
stable and the wording is not, so key on the code if you key on anything.

A finding under a `schedule-*` code comes from planning the document: a delay
broken, a `rw:leadBefore` naming no step, two constraints that cannot both hold.
They are errors, and the fix goes on the constraint — never on the plan.

## Step 2 in detail

### First: read the rendered page, not just the import

The import gives you exactly what the site published as JSON-LD, which is
faithful but lossy. WebFetch the page as well, because the JSON-LD **drops the
ingredient section headings** ("Sauce:", "Streusel:", "To serve:") and usually
the notes. Those headings are your main clue to component boundaries.

Also mine the prose for storage, make-ahead, substitutions, and the timing
constraints below. Most of what makes a recipe scheduleable is written in the
notes and never in the structured data.

### Level 1 — quantities

Add `rw:ingredients`, one per `recipeIngredient` string, carrying
`rw:originalText` **verbatim**. Leave `recipeIngredient` untouched.

- Set `rw:measurementSystem` from the site's origin. RecipeTin Eats is `AU`
  (a 20 mL tablespoon, a 250 mL cup); most US sites are `US`. Getting this
  wrong is a 35% error on every spoon measure.
- Give `rw:mass` where the source gives grams, `rw:volume` where it gives cups
  or spoons, `rw:count` where it gives a number of things. Record **all** of
  them when the source does; they are cross-checked and disagreements are
  reported, which is the point.
- Never convert a measure the source did not give. If a line is volume-only and
  the food is not in `custom_components/recipe_wizard/data/foods.json`, add the food with an honest
  `density_confidence`, or leave it and accept the warning.
- `rw:scaling`: `linear` by default; `sublinear` for leavening, salt, spices
  and extracts; `fixed` for anything that does not change with batch size;
  `toTaste` where the source says so.
- `rw:optional: true` for anything the source hedges ("if needed", "optional").

### Level 2 — link ingredients to steps

Give every step a **semantic** `@id` — `#bloom-spices`, `#whip-to-emulsion` —
never `#step-3`. Positional ids break every patch that targets them.

Add `rw:consumes` listing what each step uses. Two checks worth running on
yourself:

- **Forward**: every ingredient you link should be named in that step's text.
  This holds in all the hand-authored recipes and is the strongest signal you
  linked correctly.
- **Backward**: every ingredient named in a step's text should either be
  consumed there or reach it through a product ("add the flour" when the step
  consumes `#dry-mix`). If neither, you have missed a link.

The failure to watch for is an ingredient linked to the wrong one of several
steps that all mention it. Salt appears in four steps of the vanilla cake; the
validator cannot tell you which one is right.

### Level 3 — products, portions, constraints

**Products.** Give each step `rw:produces` naming what comes out of it, and
have the next step consume that. This is what makes the recipe a graph rather
than a list. The last step's product is the dish.

**Portions.** Whenever a thing is used more than once, say how much:

| Source says | Write |
| --- | --- |
| "half the sauce", "just over half" | `{"rw:fraction": 0.55, "rw:approximate": true}` |
| "1 cup of the crumb mixture" | `{"rw:volume": {"value": 1, "unitText": "cup"}}` |
| "the remaining batter", "reserve 2 tbsp" | `{"rw:remainder": true}` on the larger use |

Watch for the words **reserve, remaining, divided, half the, the rest**. Four
of six sample recipes split something, and it is the easiest thing to miss.

**Constraints.** This is the highest-value and least mechanical part. Mine the
prose:

| Source says | Write |
| --- | --- |
| "immediately", "do not let it sit", "work quickly" | `rw:maxDelayAfter` with `PT0S` |
| "must still be hot when incorporated" | `rw:maxDelayAfter` with a few minutes |
| "at least 3 hours before cutting", "leave to rest" | `rw:minDelayAfter` |
| "preheat 20 minutes before starting" | `rw:leadBefore` on the step that needs it |
| "while the eggs are beating, do X" | nothing — the scheduler derives this |
| "until golden and the centre jiggles" | `rw:doneness` alongside the time |
| "stop here and refrigerate overnight" | `rw:mayPauseAfter: true` |

Always give a `rw:reason`. It is what the cook is shown when a plan is refused.

**Components.** A sub-recipe with its own heading and its own method goes in
its **own file** with its own `@id`, referenced by a `rw:ComponentUse` in the
parent with `rw:requires: {"rw:batches": 1}`. Never inline it — ingredient ids
would collide, and the same sub-recipe is usually reused.

Only split out a component when it is a thing you could make on its own. A
spice blend added in one go is a component; a group of ingredients that merely
share a heading is not.

## Rules that are not negotiable

1. **Never alter a source string.** `recipeIngredient` and `rw:originalText`
   are the audit trail. Add structure alongside; do not tidy the wording.
2. **Never invent a quantity.** If a source is vague ("2 large handfuls"),
   record the vagueness. A confidently wrong number is worse than a warning.
3. **Record contradictions, do not resolve them.** Where a source's metric and
   cup columns disagree, or where two pages of the same site disagree, encode
   both and let the divergence check report it. See `#butter` in
   `recipes/chocolate-buttercream.json`.
4. **Every step needs a dependant.** A step nothing depends on floats free, and
   the backward scheduler lands it at the end of the plan — which is how a
   recipe ends up preheating its oven after the bake. Give it a product
   something consumes, or a `rw:leadBefore` on the step that needs it.
5. **Do not add `rw:covers` geometry, family swapping, or OR nodes.** These
   were considered and cut; see the end of `docs/format.md`.

## Checking yourself against ground truth

Five recipes in `recipes/` are hand-authored and trusted. To measure how good
your enrichment actually is, enrich one of them from scratch into a scratch
file and score it:

```bash
python -m recipe_wizard --import <URL> > /tmp/candidate.json
# enrich /tmp/candidate.json ...
python -m recipe_wizard --compare /tmp/candidate.json --against vanilla-cake
```

It reports precision and recall on the ingredient-to-step edges, and lists
every wrong and missed link by name. Aim for recall above 90%; a wrong link
matters more than a missing one, so precision below 95% means slow down.
