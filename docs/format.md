# The `rw:` recipe format

A JSON-LD vocabulary for recipes that can be *resolved* rather than merely
displayed: scaled to a real batch, composed out of sub-recipes, and scheduled
without ruining the food.

Every design decision below was confirmed or forced by real recipes — nine of
them, from RecipeTin Eats and Modernist Cuisine. Where the data contradicted
the design, the design changed; those places are marked **Forced by data**.
Several features were also *removed* after they turned out to serve
requirements nobody had; those are marked **Cut**.

## Scope

The primary surface is a **step-by-step cook-along**: a screen you don't have to
touch with dough on your hands, that knows what's next, what you need for it,
and what timer to start. The shopping list is second. Everything in the format
earns its place against those two, and several elegant things did not.

The library is expected to reach ~200 recipes, imported by scraping and lifted
towards level 3 by an enrichment skill. That has one large consequence: **the
validator is the contract.** It is the signal the skill iterates against, so a
rule that fires spuriously is worse than a rule that does not exist.

## Enrichment levels

| Level | What the document has |
| --- | --- |
| 0 | `recipeIngredient` strings and step text. What a scrape gives you. |
| 1 | Quantities parsed into `rw:ingredients` |
| 2 | Ingredients linked to the steps that consume them |
| 3 | Components, intermediates, constraints — a full graph |

`rw:enrichmentLevel` is declared or inferred, and **validation is gated on it**.
Firing level-3 rules at a level-0 document buries the real findings under noise
about links the document never claimed to have.

A level-0 document must still be *usable*: `recipeIngredient` strings are lifted
into ingredient rows carrying `originalText` and nothing else, so a scraped
recipe renders a real ingredient list. (It previously rendered none at all —
the loader read only `rw:ingredients`, which was data loss rather than
degradation, and fixing it outranked every modelling gap.)

## Principles

1. **The schema.org core stays valid and untouched.** Structure hangs off an
   `rw:` namespace alongside it, never replacing it.
2. **Store the source, derive the rest.** Scaling percentages, row-blocking,
   hands-on time and yields are computed, so they cannot drift.
3. **Refuse rather than guess.** A missing density, a batch below the minimum:
   these raise. A silently assumed number is worse than an error.
4. **Identity lives in `@id`.** Filenames are not identity.
5. **Semantic ids only.** `#sugar`, `#whip-to-emulsion` — never `#step-3`,
   which breaks every patch targeting it the moment a step is inserted above.

## The dataflow graph

Two node kinds — things (ingredients, intermediates, sub-recipes) and steps —
joined by `rw:consumes` and `rw:produces`.

A reference may be written as a bare fragment (`#flour`) or fully qualified
(`urn:recipe:rte/vanilla-cake#flour`), and **one rule resolves both**, for all
three id namespaces and every edge. This is not cosmetic. Each module used to
match ids its own way, so the same document read differently depending on who
was reading it: a fully-qualified `rw:consumes` resolved as an ingredient and
failed as a component in the same function, and a `rw:minDelayAfter` whose
`rw:from` named its step the long way had its edge dropped altogether — the
brownies' three-hour chill silently became "cut them now", which is the exact
failure `minDelayAfter` exists to prevent.

### Portions

**Forced by data**, in four of six recipes, three different ways:

```json
"rw:consumes": [
  {"@id": "#bolognese",     "rw:portion": {"rw:fraction": 0.55, "rw:approximate": true}},
  {"@id": "#crumb",         "rw:portion": {"rw:volume": {"value": 1, "unitText": "cup"}}},
  {"@id": "#peanut-butter", "rw:portion": {"rw:remainder": true}}
]
```

A step used to either take all of something or none of it. That renders the
whole 250 g of peanut butter against step 2 and leaves step 12's *"dollop 2 tbsp
across the surface"* with no ingredient at all — and tells the cook, at the very
first prompt, to use all the peanut butter.

Portions are **display-only** and never resolved to a mass. Nobody weighs half a
Bolognese, and a confidently wrong "1,612 g" is worse than "just over half".
Fractions are scale-invariant; absolute measures scale. `remainder` is exact for
fractions (`1 − Σ others`) and renders as "the rest" otherwise.

Validation: fractions of one target sum to ≤ 1, at most one step claims the
remainder, and a target used by several steps that all claim the whole is
flagged. That last rule found a genuine split in the cake that had been written
by hand after the gap was already known about.

### What the graph gives you free

**The Modernist table layout.** An ingredient's row-block is decided by the
first step consuming it; the block's span runs to the next block's first use;
the block's result is what its last step produces. `blocks()` reproduces the
book's layout from the graph.

**The answer to "should there be a RESULT column?"** No. Intermediates already
appear in the left-hand column when consumed — exactly how Modernist prints
*"Stove-Top Carotene Butter (see page 121)"* — so a sixth column would be mostly
empty. They render as a labelled rule closing each block.

## Scheduling

**The default is just-in-time, not earliest-start.** This is the single largest
correction the real data forced.

Earliest-start is the intuitive algorithm and it is wrong for cooking, twice
over in the same way. The cake's butter and milk have no predecessor, so ASAP
melts them at t=0 — half an hour before they are folded in, breaking *"ensure
milk and butter are hot when incorporated"*. The brownies' chocolate batter has
nothing forcing it after the two-hour freeze, so ASAP mixes it first and leaves
it to set solid. Prep that *can* happen early usually *should not*.

So the planner schedules backwards from the finish. `maxDelayAfter` is left to
handle the genuinely hard cases rather than every ordinary one.

| Property | Meaning |
| --- | --- |
| `rw:maxDelayAfter` | Ceiling on the gap after another step. `PT0S` = a rigid chain |
| `rw:minDelayAfter` | Floor. The brownies must chill ≥3 hrs before cutting |
| `rw:leadBefore` | Another step must *start* this far ahead (the oven preheat) |
| `rw:attention` | `active` / `passive` / `unattended`, per step |
| `rw:doneness` | The state that actually decides when a step is done |
| `rw:mayPauseAfter` | A sanctioned stopping point |

`minDelayAfter` was missing entirely from the first design, and its absence
produced advice as bad as the batter-made-ahead case, just in the other
direction: cut the brownies straight out of the oven.

**Every step needs something depending on it.** A step nothing depends on floats
free, and under backward scheduling lands at the end — which is how the brownies
came to preheat the oven *after* baking. The validator flags these.

Everything else a plan can be wrong about — a delay broken, a lead that cannot be
met, two constraints that cannot both hold — comes back as a finding under a
`schedule-*` code, from `--plan` and `--validate` alike. See § Validation.

Hands-on and hands-off totals are computed by sweeping the timeline, not summing
durations, which double-counts overlapping branches.

### The cook-along

`cookalong.py` is the join the primary surface needs: `resolve_dish()` for the
effective recipe and the scale, `resolution.steps` for the portions *at* that
scale, `resolution.ingredients` for the masses, and `schedule()` for the order,
the window and the timer. It is **stateless over a cursor** — the integration
holds "which step am I on" and asks what that step is — because Home Assistant
restores its own state on restart, and two copies of one cursor is one too many.

Everything it answers comes from the **effective** document, and reaching for
`library.recipe(id)` instead is the mistake the module exists to stop. The
coffee buttercream is a pure patch list, so the renderer and the planner both
presented it as an empty ingredient table and a 0-minute plan. `Resolution.recipe`
(base + variants + local adjustments, unscaled) and `Resolution.steps` (the same
steps with absolute portions scaled) are the pair that fixes it, and `schedule()`,
`render_table()` and `step_ingredients()` each take **one** argument so a caller
cannot hand them a document and a scale that disagree. That was not theoretical:
the table read its weights off the resolution and its portions off the document,
so a doubled tray printed 500 g of peanut butter beside "dollop 2 tbsp".

**Components are grouped, not interleaved.** Every scheduling property above
names step ids inside one document, so a dish is presented as each recipe's own
ordered steps with its own plan, labelled, and the cursor walks the tree in
document order. Merging them into one timeline would mean inventing edges no
recipe states — see § Known gaps.

## The shopping list

The second surface. `shopping.py` folds a `Dish` into one line per **food**:
**merge after scaling, recursively, on `rw:food` and *not* on preparation.**
Cited components are excluded.

Doubling `recipes/vanilla-cake.json` forces every clause. Butter appears twice at
two different scales — 230 g *cut into cubes* in the cake, and 450 g in the
buttercream, whose use overrides the standalone 250 g down to 225 g. Merging
*before* scaling shops for one batch of a doubled cake; merging on the words
rather than the food asks for butter twice. So **melted butter and softened
butter are one line to buy and two things to have ready**: a `ShoppingLine` keeps
its `Contribution`s rather than a running total, `describe()` is the buy line and
`breakdown()` is the mise-en-place.

Almost none of it is arithmetic. `resolve_dish()` already returns every
`Resolution` in the tree *at its own effective scale*, so merge-after-scaling
falls out of `dish.walk()` and nothing in the fold multiplies a mass. A cited
component is in `Dish.unresolvable` and never in `Dish.components`, so "excluded"
is structural rather than a filter to remember.

**A row with no mass never merges into a numeric total.** `mass_g` is `None` for
a level-0 line lifted from a `recipeIngredient` string and for a volume whose
food the bank has no density for. "500 g flour" plus "some flour" is not 500 g of
anything, so Principle 3 applies: `total_g` is `None` the moment any contributor
could not be weighed, the partial sum is only reachable through `measured_g`
beside `unweighed`, and the line reads *"at least 500 g, plus 1 line with no
weight"*. Nothing on the class hands back a bare number for a line that has
none — and `measured_g` is `None`, not `0.0`, when nothing at all was weighed,
because "0 g flour" is the same false statement in a cheaper disguise.

**`toTaste` is an answer, not a failure to answer.** The qeema's coriander leaves
reduce to no grams with confidence `n/a`, and that is a different event from its
ginger's shaky density: the source declined to specify because for shopping it
does not matter. A to-taste contribution therefore does not count as `unweighed`
and does not suppress the total — *"1.5 g, plus more to taste"*. Filing it with
the missing densities would make a genuinely complete total refuse itself.

**An unlinked row merges with nothing, including another spelling of itself.**
Two recipes both saying "1 onion, finely chopped" with no `rw:food` stay two
lines. That is the visible cost of imperfect enrichment against the ~95% target,
and both alternatives are worse: matching on the name merges "1 onion" with "1
red onion", and matching on `(recipe, ingredient)` merges two uses of *the same*
sub-recipe while still refusing two recipes that agree — a rule nobody could
predict. An unlinked row is keyed on its position in the walk, so it is always
exactly one line.

**Optional is a flag, never a filter.** `include_optional=False` drops optional
*components*, which `Dish.walk()` already knows how to do — the qeema without the
mint yogurt, and without its share of the salt. An optional *ingredient* is
different: the buttercream's milk is optional and its food is the same milk the
cake needs 495 g of, so dropping the row would silently shrink a total the cook
does need. `ShoppingLine.optional` is true only when **every** contribution is
optional — an `all()`, not an `any()` — which is the question a shopping list
asks: *is there any way through this without buying it?*

Lines come out in first-use order — the root's own ingredient order, then each
component's new foods. Not sorted: the order a recipe lists its ingredients in is
information, and alphabetising by whichever recipe's name was seen first is a
worse order chosen less deliberately. A surface wanting aisles sorts on
`food_id`. Cited components come out separately as `to_find`, carrying the page
to find them on, per § ComponentUse's "excluded from shopping lists rather than
silently contributing nothing".

The return value is plain data with no Home Assistant in it: a `TodoListEntity`
backs a line with `describe()` and `breakdown()`, and `shopping.py` does not know
that.

## Yields and scaling

| Property | Meaning |
| --- | --- |
| `rw:yieldBasis` | `sumOfInputs` / `measured` / `stated` |
| `rw:massLossFactor` | Fraction lost to evaporation |
| `rw:covers` | What one batch covers, **in the source's own words** |
| `rw:batchConstraints` | `minYield` / `maxYield` and a `reason` |
| `rw:scaling` | Per ingredient: `linear` / `fixed` / `sublinear` (√) / `toTaste` |
| `rw:batchPolicy` | Discrete rounding — 2.25 eggs becomes 3, and the batch renormalises |

`sumOfInputs` is exact for anything uncooked and close enough elsewhere:
Modernist's carrot soup sums to 1325.5 g against a stated 1.3 kg.

Whole-recipe scaling is real and routine (doubling). A parent asks for its
components in **batches** — double the cake and the frosting goes to
`batches: 2`, propagating as a plain factor.

**Cut: coverage geometry.** The buttercream states four coverage claims and no
mass, so the resolver used to convert *"enough for a 2-layer 20 cm cake"* into
grams by computing frosted surface area. It worked, and it cost ~300 lines, four
model classes and a fudged default layer height — to serve a case (changing tin
size to rescale a component) that never came up. `rw:covers` survives as text
the cook reads; nothing computes with it.

### Vessels

**Forced by data**, and only once doubling was known to be routine. Double the
cake and you have ~2.2 kg of batter, two tins that hold 1.12 kg between them,
and a bake time that is emphatically not 60 minutes. When scale ≠ 1 the resolver
warns on capacity and refuses to scale the time, quoting the source's own table:

```json
"rw:bakeTimeByVessel": [
  {"rw:vessel": "3 x 20cm round", "totalTime": "PT22M"},
  {"rw:vessel": "2 x 23cm round", "totalTime": "PT27M"}
]
```

A lookup, never interpolated — three shallower layers bake in 22 minutes where
two deeper ones take 30.

## Variants, siblings, families

**Forced by data.** The first design said variants are patches. Chocolate
buttercream falsifies that: against the vanilla it changes butter 250→200 g,
sugar 500→~319 g, vanilla from 3 tsp required to 1 tsp optional, milk from an
optional thinner to a required ¼ cup, adds cocoa, and adds the dry ingredients
in two lots instead of three. That patch is larger than the recipe.

**The rule: a variant only if the patch touches no steps and only adds or
substitutes flavouring. Otherwise a sibling.**

Operations: `Add`, `Remove`, `Replace`, `SetQuantity`, `AmendStep`,
`ReplaceStep`, `InsertStep`, `Set`. Each targets a stable `@id`, and an
unresolvable target **raises** — checked when the *base* is saved.

**Cut: family resolution.** `rw:RecipeFamily` was justified by "a parent can ask
for any buttercream and the UI offers a swap". Nobody wants that — making the
cake with chocolate buttercream means reading both recipes. A family is now a
browsing tag; nothing resolves through it.

**Cut: OR nodes.** Two things had been conflated. The cake's six finishes change
the recipe; the qeema's rice-or-naan does not — the dish is identical either
way, and the rice scales independently. Accompaniments became `rw:servesWith`, a
flat display-only list. Intra-recipe choice was the swap case, which is cut.

## ComponentUse: the use is not the recipe

The standalone buttercream says 250 g of butter; the same author's cake says
225 g. Both call it "2 sticks" (really 226.8 g). That moves the butter-to-sugar
ratio from 1:2.0 to 1:2.22 — a real difference in stiffness. Nothing decides
which is right, so the cake records a local override on its *use*.

| Property | Meaning |
| --- | --- |
| `rw:recipe` | What is used |
| `rw:requires` | `{"rw:batches": n}` or a mass |
| `rw:optional` | Whole components can be optional — the glaze, the mint yogurt |
| `rw:adjustments` | Local patches, expressed at base yield |
| `rw:citation` | A component that is a book reference, not a document |

A cited component (*Dinner* p.308, or Modernist's *"see page 121"*) renders like
any other, raises `UnresolvableComponent` if expanded, and is excluded from
shopping lists rather than silently contributing nothing.

## Units and quantities

* `rw:measurementSystem` — `AU` / `US` / `metric`. An Australian tablespoon is
  20 mL against the US 14.79; RecipeTin Eats is Australian, so "2–4 tbsp" is
  40–80 mL. Getting this wrong is a 35% error on that line.
* `rw:canonicalUnitSystem` — which parallel column to trust.
* **Ranges.** `maxValue` makes a quantity a range: "1–3 tsp sugar, if needed",
  "8–10 slices". Steps take `rw:durationRange`. `value` is the low end and is
  what arithmetic uses.
* **`rw:form`.** *"The 3 cup measure for 350 g is for elbow macaroni only."*
  Density belongs to a food *and a form*; foods marked `form_sensitive` in the
  bank ask for one when measured by volume.

Every line may carry mass, volume and count at once. They are cross-checked and
disagreements over 5% are **reported, not resolved** — the chocolate
buttercream's own two columns differ by 18%.

## Storage

Two axes, not one:

* `rw:keeps` — edibility.
* `rw:qualityWindow` — how long it is what the recipe was aiming at. *"The cake
  will keep for 3 to 4 days. The streusel stays crunchy for 2 days, then starts
  to soften."* That is not a contradiction, and treating it as one would have
  been a false positive.
* `rw:condition` — *"unless it is very warm where you are"*, which Home
  Assistant can actually evaluate.
* `rw:unsuitableFor` — negative assertions.

Component storage is **not** inherited or intersected: the buttercream says
refrigerate and the cake says don't. The parent declares
`rw:storageOverridesComponents` and its own storage wins, and the validator
still reports the conflict.

## Order of operations

Adjustments are expressed at **base yield** and applied before scaling. Reverse
this and a parent's "make the sugar 180 g" override silently becomes wrong.

1. Load base → 2. variant chain → 3. local adjustments → 4. batch yield →
5. required amount → 6. raw scale → 7. batch policy → 8. constraints →
9. scale, honouring each ingredient's `rw:scaling` → 10. recompute what is
produced, and the leftover.

**Cut: recipe parameters.** `rw:parameters` was a designed axis of variation —
the author naming a choice ("sweetness", "heat") and the options they were
willing to sanction, each option a bundle of patch operations, selectable by a
parent through `rw:parameterSelections` on its component use. It cost a model
class, a resolver step, an option-lookup branch in `adjust.py` and a field on
three other classes. Not one of the nine recipes ever declared a parameter, so
the step ran on an empty list every time it ran at all, and the branch that
resolved a selection to an option never executed once. Where an author really
does sanction a choice, it is already a variant or a sibling.

## Validation

`python -m recipe_wizard --list --validate`. Currently nine findings, no errors,
all genuine — two unit divergences, an ambiguous "divided" salt the source never
accounts for, a storage conflict, and five requests for masses where a volume
measure is unreliable.

**A finding is one record, and it names a node.** The consumer is an enrichment
skill before it is a person, so `Finding` carries a severity, a stable `code`, the
document it is about, and the **node** a fix would be applied to: a step id, an
ingredient id, a component id, or nothing where the finding really is about the
whole document — a variant cycle, or a recipe no step produces a result for, have
no one node to point at, and inventing one would send a fixer at the wrong place.
The node is canonical under `graph.py`'s single id rule, so a caller can hand it
straight back to `RecipeGraph.node` and get the thing. It used to be the recipe id
and prose: *"steps account for only 50% of #salt-flakes"* said which of the
brownies' ten ingredient rows to edit in English and nowhere else — and two of
them are salt. `__str__` still prints one line per finding, with the node in it.

A finding about a component names the **use**, not the sub-recipe — the cake's
`#frosting`, not `urn:recipe:rte/vanilla-buttercream`, which is a different
document and usually not the one that is wrong.

**Scheduling defects are findings too, under `schedule-*` codes.** There used to
be a second, parallel record — `schedule.Violation(kind, step_id, message)`, which
was the one that carried a node — and a third shape besides, the planner's list of
bare strings. Nothing converted between them and `validate_recipe` never called
`check_plan`, so a document whose constraints contradicted each other validated
clean and misbehaved only when somebody thought to ask for a plan. `--validate`
now plans the document and checks it against its own plan: the planner satisfies
what it can, and `schedule-max-delay`, `schedule-min-delay`,
`schedule-out-of-order`, `schedule-insufficient-lead`, `schedule-unknown-lead` and
`schedule-unsettled` name what it could not. All are errors — a plan that breaks a
`maxDelayAfter` is rejected, not warned about. Gated at level 2 with the other
graph rules, because a scrape declares no constraints to contradict. It adds
nothing to today's corpus: still nine findings.

**Resolver defects are findings too, under `resolve-*` codes.** A tin that will
not hold a doubled cake, a batch below a recipe's stated minimum, a fractional
batch rounded to whole eggs, a document with no stated yield: `Resolution` used to
carry these as `warnings: list[str]`, the last part of the report that was not a
`Finding`. Which meant they could not be counted, could not reach a validation
report except flattened to one `component-warning`, and could only be told apart
by their wording — `sensor.py`, `dish.py` and four tests all keyed on a substring
of an English sentence. `resolve-vessel-capacity`, `resolve-vessel-timing`,
`resolve-batch-rounded`, `resolve-batch-policy-unusable`, `resolve-does-not-scale`,
`resolve-batch-constraint` and `resolve-yield-fallback` name them now, and
`mass.py` owns `unit-divergence` and `unresolved-mass` rather than the validator
deciding which it had by looking for the word *"disagree"* in a message another
module wrote.

These are **warnings, never errors**, and that is the one way a resolver finding
differs from the validator's: nothing is wrong with the cake, and doubling it is
still more batter than its tins hold. A resolver finding is about a document *at a
scale*, and the resolution carrying it is a real one a cook can work from.

**The tin answers the node question by not having one.** `rw:vessel` is declared
on the document; it is not an ingredient, a step or a component, so there is no id
to hand back to `RecipeGraph.node` and a step invented for it would send a fixer at
a step that is not wrong. `resolve-vessel-capacity` therefore names no node, while
`resolve-vessel-timing` — *"do not scale the time on step 15"* — names the step
whose `rw:vesselOptions` say so, and `resolve-batch-rounded` names the basis
ingredient it counted. Naming a node where there is one and nothing where there is
not is the whole rule, and it is why these were worth converting rather than
flattening into a single shrug about the batch.

**The exit status is the roll-up.** `worst_level` returns the most serious level
present, and `--validate` exits non-zero when that is an error, so the enrichment
loop can ask whether it is finished instead of parsing the printed count out of
stdout. Warnings do not fail it, on purpose: a warning reflecting a genuine
ambiguity in the source is the *correct* outcome, and a loop trying to clear one
would invent data.

**Not built: a JSON report.** What the skill's loop needs is a node it can jump
to, a stable code and a severity, and it has all three off one printed line plus
an exit status. A serialisation layer would be a second interface to keep true to
the first, for a consumer that already has what it asked for.

A shaky density is only reported when the ingredient is a meaningful part of the
batch: nobody weighs 1¼ tsp of cumin, and being 30% out on 2.6 g of a 900 g
curry buries the findings that matter. **A share is measured against the sum of
the non-optional inputs** — the same total the resolver treats as the batch —
which is load-bearing rather than an implementation detail. Divide by every line
instead and the qeema's optional cayenne and chilli inflate the denominator
until the ginger it seasons falls under the threshold and goes unreported.

## Known gaps

* **Doneness reaches the timer, and still drives nothing.** It is carried onto
  `ScheduledStep` and rendered by `CookStep.timer_label()`, so a timer now reads
  *"32 min, then check: edges firmish, centre still jiggling"* — and *"go by:
  the mint is very finely chopped"* where the source gives a state and no time.
  Shown against every step of `--plan` that has one, and in `--cook`. What is
  still missing is any *behaviour*: nothing holds a timer open waiting for the
  cook to confirm the state, nothing asks, and the schedule is still built from
  the clock alone. It is displayed, not enforced.
* **One timeline across component recipes.** Each recipe is planned on its own
  and the cook-along groups them; nothing slots the frosting into the gap while
  the cake cools. Doing it needs three things the corpus does not state:
  cross-document edges (at minimum, a component must finish before the parent
  step that consumes it, and the buttercream's "use immediately on cooled cakes"
  is a *maximum* delay in the other direction), a concurrency limit for a cook
  who cannot be in two `active` steps at once, and a reading of `rw:makeAhead`
  as a scheduling constraint rather than a note. Until those exist, interleaving
  would be invention dressed as a plan.
* **Conditional steps.** *"If the liquid evaporates excessively, add water."*
* **Package-relative quantities.** *"¾ cup coconut milk (~½ can)"* — the other
  half-can is a real pantry problem.
* **The shopping list does not know your pantry.** It says what the dish needs,
  not what you already have, and nothing subtracts the half-used bag of icing
  sugar or rounds 680 g of butter up to the three blocks a shop sells. Both need
  state the library deliberately does not hold.
* **Make-ahead can change the procedure**, not just the timing: the baked
  spaghetti is 25 min covered fresh and 50 min from frozen.
* **Oven modes.** 160 °C fan and 180 °C conventional are given as equals.
* **`rw:presentation`** is stored and respected by nothing; the renderer always
  links, never inlines.
* **`sublinear` is √**, a defensible default and nothing more.
