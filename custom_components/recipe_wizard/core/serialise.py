"""A dish as JSON, for a reader that is not Python.

The third renderer. ``render.py`` writes the table as characters, ``printing.py``
draws it on a page, and this hands the whole dish to something across an HTTP
boundary. All three read the same derivations — ``render.table``, ``schedule``,
``shopping_list_from_dish``, ``cook_along_from_dish`` — because a surface that
derives its own is how two of them come to disagree about what a recipe says.

**This is not the format.** ``docs/format.md`` describes what is on disk: a
recipe, at no scale, with its variants unapplied. What comes out of here is a
*dish* — resolved, scaled, its components expanded, its plan solved — which is
derived and disposable and could be rebuilt from the documents at any time. The
two are not alternatives and nothing here should grow toward being one.

**It is private.** The only consumer is the surface this project ships. Field
names are not a public interface, this shape carries no version, and it may
change in any release. If something outside the repo ever needs to read a dish,
that is a deliberate act — a versioned path and a design pass — and not a thing
that happened because an endpoint existed.

Everything returned is JSON-safe by construction: dicts, lists, strings, bools,
finite numbers and ``None``. No dataclasses, no ``Duration``, no ``datetime``.
Times are **seconds as numbers** rather than ISO durations, because the consumer
is a browser doing arithmetic on them, and the human string the library already
writes travels alongside rather than being reconstructed at the far end — a
timer that reads "32 min, then check: edges firmish" should say that in one place
only.
"""

from __future__ import annotations

from typing import Any

from .cookalong import CookAlong, CookStep, CursorStep, StepIngredient
from .dish import Dish
from .library import Library
from .model import Portion, Product, Storage
from .render import TableBlock, table
from .schedule import Plan, schedule
from .shopping import ShoppingLine, ShoppingList, shopping_list_from_dish
from .validate import Finding


def _clean(entry: dict[str, Any]) -> dict[str, Any]:
    """Drop the keys whose value is ``None``.

    A payload that spells out every absent thing is mostly ``null``, and the
    consumer checks for presence either way. What is *not* dropped is ``False``
    or ``0``: "the cook may not pause here" and "no pause information" are
    different, and a filter that could not tell them apart would flatten the
    distinction ``may_pause_after`` exists to carry.
    """
    return {key: value for key, value in entry.items() if value is not None}


# ---------------------------------------------------------------------------
# The pieces
# ---------------------------------------------------------------------------


def finding_json(finding: Finding) -> dict[str, Any]:
    """One finding, in the one shape the whole project reports in.

    ``node`` is canonical under ``graph.py``'s id rule, so a consumer can hand it
    straight back as the thing a fix goes on.
    """
    return _clean({
        "level": finding.level,
        "code": finding.code,
        "recipe": finding.recipe,
        "node": finding.node,
        "message": finding.message,
    })


def portion_json(portion: Portion) -> dict[str, Any]:
    """How much of a row a step takes.

    ``describe()`` and not the parts: portions are display-only and are never
    resolved to a mass (``docs/format.md`` § Portions). Sending the fraction as a
    number would invite the far end to multiply it by the row mass, which is the
    one arithmetic this project refuses to do.
    """
    return _clean({
        "text": portion.describe(),
        "whole": portion.is_whole,
        "approximate": portion.approximate or None,
    })


def ingredient_json(ingredient: StepIngredient) -> dict[str, Any]:
    """One thing the cook needs in front of them, at this batch size."""
    state = ingredient.required_state
    return _clean({
        "id": ingredient.id,
        "name": ingredient.name,
        # The library's own sentence. A consumer rebuilding "4 tbsp smooth peanut
        # butter (of 500 g)" from the parts would be the second place that rule
        # lives, and the parts are here for a surface that wants to lay them out
        # differently -- not for one that wants to write the sentence again.
        "text": ingredient.describe(),
        "portion": portion_json(ingredient.portion),
        "row_mass_g": ingredient.row_mass_g,
        "optional": ingredient.optional,
        "to_taste": ingredient.to_taste,
        "display": ingredient.display,
        "note": ingredient.note,
        "required_state": None if state is None else _clean({
            "description": state.description,
            "lead_time_s": None if state.lead_time is None else state.lead_time.seconds,
            "procedure": state.procedure,
        }),
    })


def product_json(product: Product) -> dict[str, Any]:
    return _clean({"id": product.id, "name": product.name})


def storage_json(entry: Storage) -> dict[str, Any]:
    return _clean({
        "method": entry.method,
        "keeps": None if entry.keeps is None else entry.keeps.human(),
        "keeps_s": None if entry.keeps is None else entry.keeps.seconds,
        "quality_window": (
            None if entry.quality_window is None else entry.quality_window.human()
        ),
        "quality_note": entry.quality_note,
        "condition": entry.condition,
        "note": entry.note,
    })


def step_json(entry: CursorStep) -> dict[str, Any]:
    """One position in the walk: what to do, with what, and what ends it.

    ``recipe_id`` travels with ``step_id`` because the pair is what identifies a
    step in a dish — the cake and its buttercream both have an ``#add-sugar``.
    That is the same pair a saved cursor is addressed by (ADR 0003), so a caller
    holding one of these has everything it needs to say where the cook is.
    """
    step: CookStep = entry.step
    return _clean({
        "cursor": entry.cursor,
        "of": entry.of,
        "recipe_id": entry.recipe_id,
        "label": entry.label,
        "step_id": step.step_id,
        "position": step.position,
        "text": step.text,
        "attention": step.attention,
        "start_s": step.start_s,
        "end_s": step.end_s,
        "timer_s": step.timer_s,
        "timer_max_s": step.timer_max_s,
        # "32 min, then check: edges firmish, centre still jiggling" -- the number
        # and the state that overrules it, written once, by the library.
        "timer": step.timer_label(),
        "doneness": step.doneness,
        # A step's end is decided by a state, the clock, or the cook. A surface
        # that guessed this from whether a timer was present would call "beat the
        # eggs for 30 seconds" an estimate.
        "finishes_on": step.finishes_on,
        "time_is_estimate": step.time_is_estimate or None,
        "timer_starts_when": step.timer_starts_when,
        "safety_note": step.safety_note,
        "may_pause_after": step.may_pause_after,
        "needs": [ingredient_json(i) for i in step.ingredients],
        "produces": [product_json(p) for p in step.produces],
    })


def table_json(block: TableBlock) -> dict[str, Any]:
    """One block of the Modernist table, already derived by ``render.table``."""
    return _clean({
        "rows": [
            _clean({
                "label": row.label,
                "weight": row.weight,
                "scaling": row.scaling,
                "component": row.is_component or None,
            })
            for row in block.rows
        ],
        "steps": [
            _clean({"step_id": s.id, "position": s.position, "text": s.text})
            for s in block.steps
        ],
        "result": block.result,
    })


def plan_json(plan: Plan) -> dict[str, Any]:
    """The timeline, and the four figures that partition it.

    ``waiting_s`` is not decoration: a ``minDelayAfter`` is a stretch of enforced
    waiting belonging to no attention class, and it is 195 of the brownies' 420
    minutes. The three effort figures add up to ``total_s`` exactly, which is
    what a surface printing them beside it is claiming.
    """
    return _clean({
        "total_s": plan.total_s,
        "active_s": plan.active_s,
        "unattended_s": plan.unattended_s,
        "waiting_s": plan.waiting_s,
        "state_decided_s": plan.state_decided_s,
        "steps": [
            _clean({
                "step_id": s.step_id,
                "start_s": s.start_s,
                "end_s": s.end_s,
                "attention": s.attention,
                "doneness": s.doneness,
            })
            for s in plan.steps
        ],
        "rigid_chains": [list(chain) for chain in plan.rigid_chains],
        "findings": [finding_json(f) for f in plan.findings],
    })


def shopping_line_json(line: ShoppingLine) -> dict[str, Any]:
    """One food to buy, and what each recipe wanted it for.

    ``total_g`` is deliberately absent the moment any contributor could not be
    weighed, and this does not reach for ``measured_g`` to have a number to show.
    ``text`` carries the library's own phrasing -- *"plain flour: at least 500 g,
    plus 1 line with no weight"* -- where "at least" is load-bearing and true.
    """
    return _clean({
        "food_id": line.food_id,
        "name": line.name,
        "text": line.describe(),
        "total_g": line.total_g,
        "measured_g": line.measured_g,
        "optional": line.optional,
        "to_taste": line.to_taste,
        "confidence": line.confidence,
        "breakdown": line.breakdown(),
        "from_recipes": line.from_recipes,
    })


def shopping_json(listing: ShoppingList) -> dict[str, Any]:
    return _clean({
        "label": listing.label,
        "scale": listing.scale,
        "lines": [shopping_line_json(line) for line in listing.lines],
        # Cited components carry no quantity and are reported apart from the
        # lines, because a book reference is a thing to go and find rather than a
        # thing this library is allowed to invent a mass for.
        "to_find": [
            _clean({
                "label": cited.label,
                "needed_by": cited.needed_by,
                "where": cited.where,
                "text": cited.describe(),
            })
            for cited in listing.to_find
        ],
    })


# ---------------------------------------------------------------------------
# The whole thing
# ---------------------------------------------------------------------------


def library_json(library: Library) -> dict[str, Any]:
    """The index: what there is to cook, and what merely groups it.

    Families are listed **apart from recipes** and carry their members rather
    than being choosable themselves. Nothing resolves through a family — it is a
    browsing tag — and a picker that offered ``family:buttercream`` as a thing to
    cook would be offering something no resolver accepts.
    """
    return {
        "recipes": [
            _clean({
                "id": recipe.id,
                "name": recipe.name,
                "url": recipe.url,
                "variant_of": recipe.is_variant_of,
                "family": recipe.family,
                "enrichment_level": recipe.enrichment_level,
            })
            for recipe in sorted(library, key=lambda r: r.name)
        ],
        "families": [
            _clean({
                "id": family.id,
                "name": family.name,
                "members": list(family.members),
            })
            for family in library.families.values()
        ],
    }


def dish_json(dish: Dish, *, include_optional: bool = True) -> dict[str, Any]:
    """One dish at one scale: everything a surface needs, in one fetch.

    Not sectioned behind flags the way ``dish_pdf`` is. Paper has to choose
    because a page is finite and printing the plan costs a sheet; a consumer over
    HTTP has already paid for the round trip, and every surface built on this so
    far wants the walk *and* the table *and* the plan. A flag per section would
    be four times the shapes to test for a payload measured in tens of
    kilobytes. If that stops being true, measure it and then split it.

    ``include_optional`` is not the same kind of switch. It changes what the dish
    *is* -- the qeema without its mint yogurt is a different shopping list and a
    different walk -- so it belongs to the request rather than to the rendering.
    """
    resolution = dish.resolution
    recipe = resolution.recipe
    cook: CookAlong = _cook_along(dish)
    plan = schedule(resolution)

    return _clean({
        "id": recipe.id,
        "name": recipe.name,
        "label": dish.label,
        "url": recipe.url,
        "batches": resolution.scale,
        "yield_g": resolution.batch_yield_g,
        "yield_basis": recipe.yield_basis,
        "produced_g": resolution.produced_g,
        "storage": [storage_json(entry) for entry in recipe.storage],
        "unsuitable_for": list(recipe.unsuitable_for),
        "notes": list(recipe.notes),
        "table": [table_json(block) for block in table(resolution)],
        "steps": [
            step_json(entry)
            for entry in cook.sequence(include_optional=include_optional)
        ],
        "plan": plan_json(plan),
        "shopping": shopping_json(
            shopping_list_from_dish(dish, include_optional=include_optional)
        ),
        "components": [
            _clean({
                "label": node.label,
                "recipe_id": node.resolution.recipe_id,
                "batches": node.resolution.scale,
                "summary": node.resolution.summary(),
                "produced_g": node.resolution.produced_g,
                "requested_g": node.resolution.requested_g,
                "optional": node.optional,
                "change_log": list(node.resolution.change_log),
            })
            for node in list(dish.walk())[1:]
        ],
        # Every finding the dish can produce, each paired with the *use's* label,
        # which is the only thing that says which use it belongs to when one
        # sub-recipe is used twice.
        "findings": [
            _clean({**finding_json(finding), "where": label})
            for label, finding in dish.all_findings()
        ],
    })


def _cook_along(dish: Dish) -> CookAlong:
    """Deferred, not a cycle: ``cookalong`` imports ``dish``."""
    from .cookalong import cook_along_from_dish

    return cook_along_from_dish(dish)
