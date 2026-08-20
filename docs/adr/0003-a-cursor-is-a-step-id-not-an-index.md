# A saved cursor is a step id, not an index

`SavedCursor` writes `step_recipe_id` and `step_id` down beside `cursor`, and
those two are the position of record. The integer is derived: it is what `12/16`
is made of, what the movement actions add to once the real position has been
found, and what a cursor written by an older version holds until the first move
replaces it.

The reason is the rule this project already states about documents, applied to
the one place it had not been. `CLAUDE.md`: *"Semantic ids only — `#sugar`,
`#whip-to-emulsion`, never `#step-3`, which breaks every patch targeting it the
moment a step is inserted above."* A cursor that is an index **is** `#step-3`,
and a cook-along is where it does the most damage, because the walk is not one
recipe. `cookalong.sequence()` lays out the dish's own steps and then each
component's, so the cake's twenty-one positions are its own eighteen followed by
the buttercream's three. Adding a step to `vanilla-buttercream.json` — a
different file, a recipe the cook would not say they were cooking — renumbers
every position from eighteen on. The cook holding index 20 was silently moved to
a different step, mid-bake, with nothing on the screen to say so.

That is not a hypothetical edit. The coordinator polls the recipe directory
precisely because recipes are enriched from the command line while Home
Assistant is running; `coordinator.py` argues for the poll on exactly those
grounds. The integration is built to notice documents changing under it, and
until this change it noticed and then mis-read the result.

`CookAlong.locate(recipe_id, step_id)` is the lookup, and it lives in `core/`
beside `sequence()` rather than in the integration, so the rule is tested by the
fast suite and would be true of any other caller. It takes the recipe as well as
the step because **a step id is unique in a recipe and not in a dish** — the cake
and its buttercream both have an `#add-sugar`, which is the same reason
`sensor.py` gives for a sensor state not being a step id either.

## Consequences

**Both halves had to move, and the second one is easy to miss.** The entities
read the position to know what to show; the movement actions read it to know what
"next" is one past. If the action added 1 to the saved integer while the entity
looked the step up by id, the cook would be moved from a step they were not on.
So `cursor.locate_saved` is module-level and both call it, and
`_async_previous_step` now resolves the dish where it previously did not — going
back one needs no arithmetic, but it does need to know where you are.

**`step_number` comes from the resolved step, not the saved index.** Those were
the same number before this change, so the attribute could be built from either.
A card doing its own arithmetic on it would now disagree with the state printed
beside it.

**A step deleted under the cook reads as *unknown*, where it used to read as
*finished*.** That was never a decision — it was the saved integer falling off
the end of a shorter recipe, and `CookAlong.at` returning `None` for finished and
not-started alike. *Unknown* with the reason attached is the same argument
`sensor.py` already makes for not saying *idle* when a recipe is deleted: the
cook is standing in front of a half-made tray and the integration does not know
where they are. A cook-along genuinely run off its end still reads *finished*,
because going past the last step writes no step id to lose.

**There is no migration, on purpose.** A cursor saved before this change has no
pair, falls back to the index, and starts being addressed properly the first time
the cook moves. Backfilling it on read would mean writing to the config entry
from inside a refresh, which re-enters the refresh through the entry's own update
listener; the window it would close is one upgrade during one cook-along during
one edit of a sub-recipe.

**One edge is accepted rather than solved.** A finished cook-along holds no step
id, so if a step is added to a dish the cook has already finished, the index that
was off the end lands on the new last step and the cook-along un-finishes.
Telling that apart would need a fifth saved fact, and the four exist to tell
"finished" from "not started" at all.
