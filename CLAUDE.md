# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A structured recipe format (`rw:` extensions over schema.org JSON-LD), a
dependency-free Python library that **resolves** it — scales, composes
sub-recipes, schedules, rolls up a shopping list — and a Home Assistant custom
integration wrapping that library. The library is vendored *inside* the
integration at `custom_components/recipe_wizard/core/` because HACS ships
`custom_components/recipe_wizard/` and nothing else.

Read in this order before non-trivial work: `CONTEXT.md` (the domain language —
what to call things, and what not to), `docs/format.md` (the format and why each
decision is what it is), `docs/adr/` (decisions a reader would otherwise undo).

## Commands

```bash
python -m recipe_wizard --list                                   # the library
python -m recipe_wizard vanilla-cake --components --plan          # Modernist table + schedule
python -m recipe_wizard vanilla-cake --batches 2 --cook           # the cook-along
python -m recipe_wizard vanilla-cake --batches 2 --shopping       # one line per food
python -m recipe_wizard --list --validate                         # exits non-zero on any error finding
python -m recipe_wizard --import <URL> > recipes/<slug>.json       # faithful level-0 scrape
python -m recipe_wizard --compare candidate.json --against vanilla-cake   # score an enrichment
```

`recipe_wizard.py` at the repo root is a trampoline that keeps
`python -m recipe_wizard` working; it is not part of the installed integration.

### Tests — two suites, two interpreters

```bash
python -m pytest -q                                          # library, bare Python (226 tests, ~1s)
python -m pytest tests/test_shopping.py -q                   # one file
python -m pytest tests/test_shopping.py::test_name -q        # one test

docker build -t rw-hass-test tests_ha                        # once
docker run --rm -v "$(pwd):/app" -w /app rw-hass-test \
    python -m pytest -q -o asyncio_mode=auto tests_ha        # the integration

# From Git Bash on Windows, which is where this repo is developed, prefix it:
MSYS_NO_PATHCONV=1 docker run --rm -v "$(pwd -W):/app" -w /app rw-hass-test \
    python -m pytest -q -o asyncio_mode=auto tests_ha
```

The suites **cannot share an interpreter**: the Home Assistant harness's autouse
fixtures attach to every test in the session and all 226 library tests error. The
container exists because the harness cannot run on Windows at all
(`homeassistant.runner` imports `fcntl`). `-o asyncio_mode=auto` is not optional.
CI runs both suites plus `hassfest` and HACS validation. There is no linter or
formatter configured.

Adding a recipe: see `.claude/skills/enrich-recipe/SKILL.md` (the `/enrich-recipe`
skill). The loop is import → enrich → `--validate` to zero *errors* (warnings are
for a human; a warning reflecting genuine source ambiguity is the correct outcome)
→ read `--plan`.

## Architecture

### The library (`core/`, no Home Assistant dependency, on purpose)

The pipeline is `resolve.py`, and **its step order is load-bearing** — adjustments
are expressed at base yield and applied before scaling, so reversing them silently
corrupts a parent's override. The module docstring lists all ten steps;
`docs/format.md` §"Order of operations" says why.

- `model.py` — the on-disk format and its readers. Every `parse` classmethod sits
  with the type it builds; ADR 0001 says why this ~800-line module stays one file.
- `graph.py` — the indexed `rw:consumes`/`rw:produces` dataflow graph, built once
  per recipe and **the single place a reference is resolved**, whether written as a
  bare fragment (`#flour`) or fully qualified. Every other module asks it rather
  than walking; each module matching ids its own way is how the brownies' three-hour
  chill once silently became "cut them now".
- `resolve.py` → `Resolution` (one recipe at one scale). `Resolution.recipe` is the
  **effective recipe** — base + variant chain + local adjustments. A variant may be
  nothing but a patch list on disk, so a caller reading `library.recipe(id)` instead
  gets an empty table and a 0-minute plan.
- `dish.py` → `Dish`: a recipe resolved with its components, recursively. Not
  strict — "a dish is built to be shown", so an impossible batch comes back as a
  `resolve-batch-constraint` finding on the resolution rather than an exception.
  `all_findings()` pairs each with the *use's* label, which is the only thing that
  says which use a finding belongs to when one sub-recipe is used twice.
- `mass.py` — unit reconciliation and the **one** definition of the batch total.
  A line with no derivable mass never disappears into a total: `total_g` is `None`
  and the line reads "at least 500 g, plus 1 line with no weight".
- `schedule.py` — just-in-time, scheduled **backwards from the finish**, never
  earliest-start (which melts the cake's butter half an hour early).
- `cookalong.py` — the primary surface. **Stateless over a cursor**: the caller
  holds which step it is on.
- `shopping.py` — merges on **food alone, never on preparation**, and after scaling.
- `validate.py` — `Finding` is the only report shape in the project, and four
  modules produce it: `validate.py`, `schedule.py` (`schedule-*`), `resolve.py`
  (`resolve-*`) and `mass.py` (`unit-divergence`, `unresolved-mass`). **The
  producer decides the level and the code**, never the module printing them — the
  validator used to classify a mass finding by looking for the word "disagree" in
  a sentence `mass.py` wrote. `Finding` lives in `validate.py` and the other three
  import it inside the functions that build one, because `validate` imports them
  at module scope and an import back would be a cycle. Findings are **gated on
  enrichment level**
  (0–3), and every one names the **node** a fix goes on, canonical under `graph.py`'s
  id rule so a caller can hand it straight back to `RecipeGraph.node`. The validator
  is the contract an enrichment agent iterates against, so **a rule that fires
  spuriously is worse than no rule at all**.
- `render.py` (the Modernist table, derived from the graph, never authored),
  `adjust.py`, `units.py`, `duration.py`, `importer.py`, `compare.py`.

`core/__init__.py` re-exports the public surface with an explicit `__all__`; keep it
in step when adding one.

### The integration

`__init__.py` (setup/unload) → `coordinator.py` (`RecipeLibraryCoordinator`, whose
`.data` is a plain `core.library.Library`; `entry.runtime_data` is a
`RecipeWizardData` dataclass, never `hass.data[DOMAIN]`) → `entity.py` (one base
class, one `SERVICE` device, identity taken from `entry_id`) → `sensor.py`,
`todo.py`. `cursor.py` holds cook-along state, `actions.py` registers the four
cook-along actions, and `loader.py` is the load path shared by the config flow and
the coordinator.

Four invariants:

1. **No `homeassistant` import at module scope in `__init__.py`** (ADR 0002).
   Importing `core` runs that module first, so a top-level HA import would make the
   CLI and all 226 library tests need a 300 MB dependency. Use `TYPE_CHECKING` plus
   function-body imports there, and *only* there — every other integration module is
   imported only by Home Assistant and imports normally at module scope.
   `tests/test_packaging.py` enforces it in a subprocess; if that test goes red after
   someone tidies the imports, the test is right and the tidying is wrong. A known
   consequence: hassfest warns about a missing `CONFIG_SCHEMA` and we accept it.
2. **Every call into the library goes through `hass.async_add_executor_job`** —
   `Library.load()` reads files. Never resolve anything in an entity property;
   `native_value` is called on every state write, which is why `cursor.py` caches the
   resolved dish once per (recipe, batches, library).
3. **The cursor lives in the config entry's options**, written through
   `async_update_entry` (which is also what notifies the sensors), so a restart
   during the brownies' three-hour chill comes back to the chill.
4. **A sensor state is a position (`12/16`), not step text** — Home Assistant caps a
   state at 255 characters and silently drops longer writes.

`quality_scale.yaml` records where the integration stands against the Home Assistant
quality scale, exemption by exemption; keep it honest when adding a rule-relevant
feature.

### Data and layout

`recipes/` sits *beside* `custom_components/` because recipes are the user's data —
the repo root when developing, the Home Assistant config directory once installed.
`custom_components/recipe_wizard/data/foods.json` (the food bank) is inside, because
the integration needs it at runtime.

## Conventions

- **Use `CONTEXT.md`'s vocabulary in code, tests, docs and commit messages.** The
  distinctions are load-bearing: a *component* is a parent's *use* of a sub-recipe,
  never the sub-recipe and never a unit of software; a *dish* is not a plan; a *food*
  is not an ingredient.
- Semantic ids only — `#sugar`, `#whip-to-emulsion`, never `#step-3`, which breaks
  every patch targeting it the moment a step is inserted above.
- Docstrings here carry the *reasoning*, including what was tried and rejected. Match
  that: when a decision would look wrong to a future reader, say why in the module
  docstring, and add an ADR under `docs/adr/` if it is one a reviewer would reverse.
- Tests either build their own premise with `tests/support.py` (which round-trips
  through `Recipe.parse`, so a test cannot assert behaviour no document can produce)
  or run against the real corpus where the corpus *is* the subject. Name them after
  the failure mode: `test_an_unweighed_row_does_not_disappear_into_a_total`.
- Speculative generality gets cut, and the cut is recorded with its reasoning
  (coverage geometry, OR nodes, recipe parameters, `go_to_step` — see the README and
  `docs/format.md`). Prefer removing an unexercised axis to keeping it.
- Commits are prose: an imperative summary line, then paragraphs on what the data
  forced and what was rejected. Merge commits say what the merge itself broke.
