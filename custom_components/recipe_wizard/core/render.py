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

Every one of those three rules is a question about the graph, and this module
asks ``graph.py`` rather than walking it. It used to rebuild a
``{product_id: label}`` map on every ``ingredients_for_step`` call -- once per
step of a cook-along walk -- and call ``uses_of`` inside its per-ingredient loop,
which made the table O(ingredients x steps).
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from textwrap import wrap

from .graph import GraphSource, recipe_graph
from .model import Portion, Recipe, Step
from .resolve import Resolution

INFINITY = 10**9


@dataclass(slots=True)
class Block:
    """One row-block: some ingredients, the steps that first use them, a result."""

    ingredient_ids: list[str] = field(default_factory=list)
    steps: list[Step] = field(default_factory=list)
    result: str | None = None
    first_use: Step | None = None
    """The step that put this block here, and the block's own identity.

    This and ``steps`` used to be a second list kept hand-in-hand with
    ``grouped``, indexed together with nothing enforcing that they stayed the
    same length. It also held a *position number*, so two things first used by
    two different steps that shared a ``position`` were filed as one block.
    ``None`` for things no step ever uses, and for the head block of steps that
    run before any ingredient appears.
    """


def first_use(source: GraphSource) -> dict[str, int]:
    """The position of the earliest step consuming each id."""
    graph = recipe_graph(source)
    return {ref: step.position for ref, step in graph.first_use_steps.items()}


def uses_of(source: GraphSource, ref: str) -> list[tuple[Step, Portion]]:
    """Every step that takes some of ``ref``, with how much it takes."""
    return [(use.step, use.portion) for use in recipe_graph(source).consumers(ref)]


def ingredients_for_step(
    source: GraphSource, step_id: str
) -> list[tuple[str, str, Portion]]:
    """What to put in front of the cook at one step: id, label, how much.

    This is the reason portions exist. Without them it returns all 250 g of
    peanut butter at step 2 and nothing at all at step 12's "dollop 2 tbsp
    across the surface".

    Deliberately answers for a bare ``Recipe`` and returns portions exactly as
    the document states them, at base yield. A level-0 scrape has no resolution
    and still has to render, so this form has to keep working. It is *not* the
    form to call when a scale is in play: use ``cookalong.step_ingredients``,
    which takes a ``Resolution`` and nothing else, so the document, the portions
    and the masses cannot come from three different batches.
    """
    return [
        (entry.ref, entry.label, entry.portion)
        for entry in recipe_graph(source).step_inputs(step_id)
    ]


def blocks(source: GraphSource) -> list[Block]:
    """Group ingredients by the step that first uses them, and hand it its steps."""
    graph = recipe_graph(source)
    recipe = graph.recipe

    entries = [(ing.id, graph.first_use(ing.id)) for ing in recipe.ingredients]
    entries += [(c.id, graph.first_use(c.id)) for c in recipe.components]
    # Stable, so things sharing a first use keep the order the document lists
    # them in. Anything never consumed sorts to the end and shares one block.
    entries.sort(key=lambda pair: INFINITY if pair[1] is None else pair[1].position)

    grouped: list[Block] = []
    for thing_id, step in entries:
        # Grouped on the step itself, not on its number. Two ingredients first
        # used by two *different* steps belong in two blocks even if a document
        # numbers both steps the same.
        if grouped and grouped[-1].first_use is step:
            grouped[-1].ingredient_ids.append(thing_id)
        else:
            grouped.append(Block(ingredient_ids=[thing_id], first_use=step))

    ordered_steps = graph.ordered_steps
    order = {step.id: index for index, step in enumerate(ordered_steps)}
    for index, block in enumerate(grouped):
        if block.first_use is None:
            continue
        start = order[block.first_use.id]
        following = next(
            (b.first_use for b in grouped[index + 1:] if b.first_use is not None), None
        )
        # The span runs to just before the next block's first use. Sliced by
        # order rather than by position arithmetic, so a repeated position number
        # cannot hand two blocks the same steps.
        end = len(ordered_steps) - 1 if following is None else order[following.id] - 1
        block.steps = list(ordered_steps[start:end + 1])
        if block.steps:
            # A block's result is what its *last* step produces -- and its first
            # product, where a step emits several. That rule exists nowhere else
            # in the system: it is the table's own, and it is what closes a block
            # with "-> Buttercream base" instead of a sixth column.
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


@dataclass(slots=True)
class Row:
    """One left-column line: what it is, what it weighs, what share of the basis."""

    label: str
    weight: str
    scaling: str
    is_component: bool = False


@dataclass(slots=True)
class TableBlock:
    """A block with its left column already derived. What the table *means*,
    before anything decides whether it is going to be characters or points."""

    rows: list[Row] = field(default_factory=list)
    steps: list[Step] = field(default_factory=list)
    result: str | None = None


def table(source: Recipe | Resolution) -> list[TableBlock]:
    """The table as data, for a renderer to lay out however it draws.

    Split out of ``render_table`` when the PDF surface arrived. The rules that
    decide a row -- a component prints its label and no weight, an ingredient
    used twice says so, scaling is against ``scaling_basis`` and is absent when
    there is no basis to divide by -- are the table's own, and a second renderer
    reimplementing them is how two surfaces come to disagree about what the
    recipe says. ``render_table`` formats this; ``printing.py`` draws it.
    """
    graph = recipe_graph(source)
    recipe = graph.recipe
    resolution = None if isinstance(source, Recipe) else source
    masses = {i.id: i for i in resolution.ingredients} if resolution else {}

    basis_mass = None
    if recipe.scaling_basis and recipe.scaling_basis in masses:
        basis_mass = masses[recipe.scaling_basis].mass_g

    out: list[TableBlock] = []
    for block in blocks(graph):
        rows: list[Row] = []
        for ingredient_id in block.ingredient_ids:
            resolved = masses.get(ingredient_id)
            component = graph.component(ingredient_id)
            is_component = component is not None
            if component is not None:
                label, weight, scaling = f"{component.label} (sub-recipe)", "-", "-"
            elif resolved is not None:
                label = resolved.name + (" (optional)" if resolved.optional else "")
                weight = (
                    "to taste" if resolved.to_taste else format_mass(resolved.mass_g)
                )
                scaling = "-"
                if basis_mass and resolved.mass_g is not None:
                    scaling = f"{resolved.mass_g / basis_mass:.1%}"
            else:
                ing = graph.ingredient(ingredient_id)
                label = ing.name if ing else ingredient_id
                weight = str(ing.mass) if ing and ing.mass else "-"
                scaling = "-"

            # Flag anything used more than once, so the table does not imply
            # the whole amount goes in at its first appearance.
            uses = graph.consumers(ingredient_id)
            if len(uses) > 1:
                label += f" (in {len(uses)} parts)"
            rows.append(Row(label, weight, scaling, is_component))
        out.append(TableBlock(rows=rows, steps=block.steps, result=block.result))
    return out


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
    name_w, weight_w, scale_w = 26, 9, 8
    proc_w = max(30, width - name_w - weight_w - scale_w - 6)

    lines: list[str] = []
    header = (
        f"{'INGREDIENT':<{name_w}} {'WEIGHT':>{weight_w}} {'SCALING':>{scale_w}}  "
        f"{'PROCEDURE'}"
    )
    lines.append(header)
    lines.append("=" * min(width, len(header) + proc_w - len("PROCEDURE")))

    for block in table(source):
        left: list[str] = []
        for entry in block.rows:
            for row, chunk in enumerate(wrap(entry.label, name_w) or [""]):
                if row == 0:
                    left.append(f"{chunk:<{name_w}} {entry.weight:>{weight_w}} "
                                f"{entry.scaling:>{scale_w}}")
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
