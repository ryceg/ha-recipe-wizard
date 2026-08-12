"""Rendering the Modernist Cuisine table layout from the dataflow graph.

The layout that started this: ingredients on the left, blocked against the
numbered steps that first consume them, with a rule between blocks. The point
of building the graph is that none of that blocking is authored. It falls out:

* an ingredient's block is decided by the *first* step that consumes it
* a block's step span runs to just before the next block's first use
* a block's result is whatever its last step produces

So the "RESULT column" question answers itself. Intermediates already appear in
the left column when they are consumed -- which is exactly how Modernist prints
"Stove-Top Carotene Butter, see page 121" -- and a sixth column would be mostly
empty. They are shown instead as a labelled rule closing each block.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from textwrap import wrap

from .model import Portion, Recipe, Step
from .resolve import Resolution
from .schedule import effective_recipe

INFINITY = 10**9


@dataclass(slots=True)
class Block:
    """One row-block: some ingredients, the steps that first use them, a result."""

    ingredient_ids: list[str] = field(default_factory=list)
    steps: list[Step] = field(default_factory=list)
    result: str | None = None


def first_use(recipe: Recipe) -> dict[str, int]:
    """The position of the earliest step consuming each id."""
    out: dict[str, int] = {}
    for step in sorted(recipe.steps, key=lambda s: s.position):
        for ref in step.consumed_ids:
            out.setdefault(ref, step.position)
    return out


def uses_of(recipe: Recipe, ref: str) -> list[tuple[Step, Portion]]:
    """Every step that takes some of ``ref``, with how much it takes."""
    out = []
    for step in sorted(recipe.steps, key=lambda s: s.position):
        portion = step.portion_of(ref)
        if portion is not None:
            out.append((step, portion))
    return out


def ingredients_for_step(
    recipe: Recipe, step_id: str
) -> list[tuple[str, str, Portion]]:
    """What to put in front of the cook at one step: id, label, how much.

    This is the reason portions exist. Without them it returns all 250 g of
    peanut butter at step 2 and nothing at all at step 12's "dollop 2 tbsp
    across the surface".

    Deliberately takes a bare ``Recipe`` and returns portions exactly as the
    document states them, at base yield. A level-0 scrape has no resolution and
    still has to render, so this form has to keep working. It is *not* the form
    to call when a scale is in play: use ``cookalong.step_ingredients``, which
    takes a ``Resolution`` and nothing else, so the document, the portions and
    the masses cannot come from three different batches.
    """
    step = recipe.step(step_id)
    if step is None:
        return []
    products = {
        product.id: product.name or product.id
        for other in recipe.steps
        for product in other.produces
    }
    out: list[tuple[str, str, Portion]] = []
    for consumed in step.consumes:
        ingredient = recipe.ingredient(consumed.ref)
        if ingredient is not None:
            out.append((consumed.ref, ingredient.name, consumed.portion))
            continue
        component = next((c for c in recipe.components if c.id == consumed.ref), None)
        if component is not None:
            out.append((consumed.ref, component.label, consumed.portion))
            continue
        # Intermediates count too: "half the brownie batter" is exactly the
        # kind of thing the cook needs told, and it is not an ingredient.
        if consumed.ref in products:
            out.append((consumed.ref, products[consumed.ref], consumed.portion))
    return out


def blocks(recipe: Recipe) -> list[Block]:
    """Group ingredients by first use, and hand each group its steps."""
    uses = first_use(recipe)
    entries = [(ing.id, uses.get(ing.id, INFINITY)) for ing in recipe.ingredients]
    entries += [(c.id, uses.get(c.id, INFINITY)) for c in recipe.components]
    entries.sort(key=lambda pair: pair[1])

    grouped: list[Block] = []
    starts: list[int] = []
    for ingredient_id, position in entries:
        if grouped and starts[-1] == position:
            grouped[-1].ingredient_ids.append(ingredient_id)
        else:
            grouped.append(Block(ingredient_ids=[ingredient_id]))
            starts.append(position)

    ordered_steps = sorted(recipe.steps, key=lambda s: s.position)
    for index, block in enumerate(grouped):
        start = starts[index]
        if start >= INFINITY:
            continue
        following = [s for s in starts[index + 1:] if s < INFINITY]
        end = following[0] - 1 if following else ordered_steps[-1].position
        block.steps = [s for s in ordered_steps if start <= s.position <= end]
        if block.steps:
            produced = block.steps[-1].produces
            if produced:
                block.result = produced[0].name or produced[0].id

    # Steps before the first ingredient use (preheating, lining pans) would
    # otherwise vanish. Give them a block of their own at the top.
    covered = {s.id for b in grouped for s in b.steps}
    orphans = [s for s in ordered_steps if s.id not in covered]
    if orphans:
        grouped.insert(0, Block(ingredient_ids=[], steps=orphans))
    return grouped


def format_mass(grams: float | None) -> str:
    """Mass for display. Small quantities need a decimal or they read as zero."""
    if grams is None:
        return "-"
    if grams < 10:
        return f"{grams:.1f} g"
    return f"{grams:.0f} g"


def render_table(
    source: Recipe | Resolution,
    *,
    width: int | None = None,
) -> str:
    """Render the blocked ingredient/procedure table as plain text.

    One argument, on purpose. This used to take a recipe *and* a resolution and
    read the weight column off the resolution while reading the procedure
    column, the row-blocking and every portion off the recipe. For a variant
    that meant an empty table — the coffee buttercream's document has no
    ingredients and no steps of its own — and at scale ≠ 1 it meant a doubled
    mass printed against a single batch's "dollop 2 tbsp". Both columns now come
    from ``effective_recipe(source)``, which is the same document at the same
    scale by construction.
    """
    width = width or min(shutil.get_terminal_size((100, 24)).columns, 110)
    resolution = None if isinstance(source, Recipe) else source
    recipe = effective_recipe(source)
    masses = {}
    if resolution:
        masses = {i.id: i for i in resolution.ingredients}

    basis_mass = None
    if recipe.scaling_basis and recipe.scaling_basis in masses:
        basis_mass = masses[recipe.scaling_basis].mass_g

    name_w, weight_w, scale_w = 26, 9, 8
    proc_w = max(30, width - name_w - weight_w - scale_w - 6)

    lines: list[str] = []
    header = (
        f"{'INGREDIENT':<{name_w}} {'WEIGHT':>{weight_w}} {'SCALING':>{scale_w}}  "
        f"{'PROCEDURE'}"
    )
    lines.append(header)
    lines.append("=" * min(width, len(header) + proc_w - len("PROCEDURE")))

    for block in blocks(recipe):
        left: list[str] = []
        for ingredient_id in block.ingredient_ids:
            resolved = masses.get(ingredient_id)
            component = next(
                (c for c in recipe.components if c.id == ingredient_id), None
            )
            if component is not None:
                label = f"{component.label} (sub-recipe)"
                weight = "-"
                scaling = "-"
            elif resolved is not None:
                label = resolved.name + (" (optional)" if resolved.optional else "")
                weight = "to taste" if resolved.to_taste else format_mass(resolved.mass_g)
                scaling = "-"
                if basis_mass and resolved.mass_g is not None:
                    scaling = f"{resolved.mass_g / basis_mass:.1%}"
            else:
                ing = recipe.ingredient(ingredient_id)
                label = ing.name if ing else ingredient_id
                weight = str(ing.mass) if ing and ing.mass else "-"
                scaling = "-"

            # Flag anything used more than once, so the table does not imply
            # the whole amount goes in at its first appearance.
            uses = uses_of(recipe, ingredient_id)
            if len(uses) > 1:
                label += f" (in {len(uses)} parts)"
            for row, chunk in enumerate(wrap(label, name_w) or [""]):
                if row == 0:
                    left.append(f"{chunk:<{name_w}} {weight:>{weight_w}} "
                                f"{scaling:>{scale_w}}")
                else:
                    left.append(f"{chunk:<{name_w}} {'':>{weight_w}} {'':>{scale_w}}")

        right: list[str] = []
        for step in block.steps:
            marker = f"{step.position:>2}. "
            for row, chunk in enumerate(wrap(step.text, proc_w - len(marker)) or [""]):
                right.append((marker if row == 0 else " " * len(marker)) + chunk)

        for row in range(max(len(left), len(right))):
            l = left[row] if row < len(left) else " " * (name_w + weight_w + scale_w + 2)
            r = right[row] if row < len(right) else ""
            lines.append(f"{l}  {r}".rstrip())

        if block.result:
            lines.append(f"{'':<{name_w + weight_w + scale_w + 4}}-> {block.result}")
        lines.append("-" * min(width, 100))

    return "\n".join(lines)
