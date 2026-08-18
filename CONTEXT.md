# Recipe Wizard

The domain language of the `rw:` recipe format and the library that resolves it.
`docs/format.md` says *why* each decision is what it is; this file fixes *what to
call things* so the code, the tests, the docs and the commit log agree.

## Language

### Documents and identity

**Recipe**:
One document. Identity lives in its `@id`, never its filename.
_Avoid_: dish (that is a different term below), file, entry.

**Effective recipe**:
The recipe a resolution is actually true of — base, plus the variant chain, plus
any local adjustments, before scaling. Carried on `Resolution.recipe`.
_Avoid_: materialised recipe, the real recipe, resolved recipe.

**Variant**:
A recipe expressed as a patch on another, permitted only when the patch touches
no steps and only adds or substitutes flavouring. On disk it may be nothing but
a patch list — the coffee buttercream has no ingredients and no steps of its own.
_Avoid_: override, subclass, derived recipe.

**Sibling**:
A recipe that fills the same role as another without being a patch on it.
Chocolate and vanilla buttercream are siblings; neither is a variant.
_Avoid_: alternative, version.

**Family**:
A browsing tag grouping siblings. Nothing resolves through one.
_Avoid_: category, group, collection.

**Component**:
A parent recipe's **use** of a sub-recipe (`rw:ComponentUse`) — not the sub-recipe
itself. The distinction is load-bearing: the standalone buttercream says 250 g of
butter and the cake's use of it says 225 g. Never used in this project to mean a
unit of software.
_Avoid_: sub-recipe (that is the recipe a component points at), child, module.

**Cited component**:
A component whose recipe is a book reference rather than a document. It renders,
it is never expanded, and the shopping list leaves it off deliberately.
_Avoid_: external recipe, missing recipe, unresolved component.

**Enrichment level**:
How far a document has been lifted, 0 to 3. Validation is gated on it.
_Avoid_: quality, completeness, tier.

### The dataflow graph

**Recipe graph**:
The indexed view of one recipe's `rw:consumes` / `rw:produces` edges. Built once
per recipe from the effective document, and the single place that resolves a
reference written either as a bare fragment or fully qualified.
_Avoid_: DAG, dependency tree, index.

**Portion**:
How much of a thing one step takes — a fraction, a measure, or the remainder.
Display-only, and never resolved to a mass.
_Avoid_: amount, share, quantity.

**Product**:
An intermediate a step emits, and a node in the graph like any ingredient.
_Avoid_: output, result (except as the Modernist table's own column of that name).

**Block**:
One row-block of the Modernist table: the things a step first uses, the steps
they span, and the result closing it. Derived from the graph, never authored.
_Avoid_: section, group, row group.

### Resolving and scaling

**Resolution**:
One recipe at one scale, with real masses and the effective document it came from.
_Avoid_: instance, computed recipe, output.

**Dish**:
A recipe resolved together with its components, recursively — the thing a cook
actually makes. `resolve_dish()` returns one; the shopping list folds over it.
_Avoid_: meal, tree, plan (a plan is a schedule), recipe.

**Batches**:
What a parent asks a component for, and what a cook asks the library for.
Doubling propagates as a plain factor.
_Avoid_: multiplier, quantity, servings.

**Mass table**:
Every line's mass for one recipe, computed once, with why each is uncertain and
the one definition of the batch total.
_Avoid_: weights, masses dict, totals.

**Yield**:
What a batch makes. `sumOfInputs`, `measured` or `stated`, per the document.
_Avoid_: output, size, amount.

**Food**:
A food concept in the bank, distinct from the words a recipe uses for it. The
thing a shopping list merges on — and it merges on food alone, never on
preparation, so melted and softened butter are one line to buy.
_Avoid_: ingredient (that is a line of a recipe), item, product.

**Shopping line**:
One food to buy, and every recipe in the dish that wants some of it, merged
after scaling. Merged on food alone — never on preparation, so melted and
softened butter are one line.
_Avoid_: item, row, entry, ingredient.

**Contribution**:
One recipe's ingredient row as its share of a shopping line. What makes the
merged line able to say which recipes wanted it and how each one prepares it.
_Avoid_: source, part, component (that word means something else here).

### Cooking

**Cook-along**:
The primary surface: each step in the order it is to be done, what it needs at
this batch size, and what its timer should say. Stateless over a cursor — the
caller holds which step it is on.
_Avoid_: session, wizard, walkthrough, mode.

**Plan**:
A recipe's steps placed on a timeline, scheduled backwards from the finish.
_Avoid_: schedule (the verb is fine), timeline, itinerary.

**Doneness**:
The state that decides when a step is finished. Where a source gives both a state
and a time, the state is authoritative and the time is an estimate.
_Avoid_: test, check, condition.

**Attention**:
Whether the cook can walk away: `active`, `passive`, `unattended`.
_Avoid_: effort, involvement, busy.

**Finishes on**:
What ends a step: a `state` (a doneness, and any stated time is an estimate of
it), the `clock` (a time and no state, so the time is the instruction), or the
`cook` (neither, so it is done when they have done it). One property, because
every surface used to decide it privately and they disagreed.
_Avoid_: timer type, step kind, is_timed.

**Rigid chain**:
A run of steps that may not be interrupted, from a `maxDelayAfter` of zero.
_Avoid_: critical path, locked sequence.

### Reporting

**Finding**:
One thing wrong with a document: a severity, a stable code, the recipe, and the
node it is about. The validator is the contract an enrichment agent iterates
against, so a finding that fires spuriously is worse than no rule at all.
Produced by the validator, the planner, the resolver and the mass table alike —
it is the only report shape in the project, and the producer decides the code
rather than whoever prints it.
_Avoid_: error, warning, violation, issue, diagnostic.

**Resolver finding**:
A finding about a document *at a scale* — the tins will not hold a doubled cake,
the batch was rounded to whole eggs. Always a warning: nothing is wrong with the
document, and the resolution carrying it is one a cook can work from. Where its
subject is the batch rather than a line, it names no node.
_Avoid_: warning (the field was called that, and the word hid what it was).

**Node**:
What a finding is about — an ingredient, a component use, or a step — named by
the id the recipe graph files it under, so a caller can look it up rather than
parse the message.
_Avoid_: location, target, path.
