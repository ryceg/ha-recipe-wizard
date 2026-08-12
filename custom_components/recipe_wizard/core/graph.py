"""One index over the dataflow graph, built once and asked questions.

``docs/format.md`` § "The dataflow graph" describes two node kinds -- things
(ingredient rows, sub-recipe uses, intermediates) and steps -- joined by
``rw:consumes`` and ``rw:produces``. Five modules used to answer questions about
that graph by walking it, each in its own shape, and the shapes had drifted:

* *"what does this step consume"* was walked in eight places.
* *"who produces this id"* existed three incompatible ways at once: a
  ``dict[product_id, step_id]`` in the planner, a ``dict[product_id, label]`` in
  the renderer -- **rebuilt on every call**, so once per step of a cook-along
  walk -- and a bare ``set`` twice in the validator.
* ``dependencies(recipe)`` was recomputed three times per ``schedule()`` call and
  ``{step.id: step}`` was rebuilt four times across two modules.

And the drift had already produced a bug. ``Recipe.ingredient()`` and
``Recipe.step()`` are fragment-tolerant -- they accept
``urn:recipe:rte/vanilla-cake#frosting`` as readily as ``#frosting`` -- but there
was no ``Recipe.component()``, so ``render.ingredients_for_step`` resolved an
ingredient through the tolerant lookup and then matched a component with
``c.id == ref`` on the next line. One function, two rules, and a
fully-qualified reference that worked for an ingredient and vanished for a
sub-recipe. ``schedule.py`` had the same split: ``dependencies`` matched a
``maxDelayAfter``'s target by exact dict key while ``_edge_gap`` looked the same
target up through the tolerant ``recipe.step()``, so an edge the planner had
refused to draw could still have a mandatory wait looked up for it.

So the questions live here, over one set of indexes, with **one** tolerance rule:
``model.fragment`` -- try the reference as written, then its fragment. That is
exactly what ``Recipe.ingredient()`` always did; what changed is that a
component and an intermediate now get the same courtesy, and that a resolved
reference is reported under the *node's* id rather than the spelling the step
happened to use, so a caller keying masses by ingredient id finds them either
way.

**Built by the caller that needs it, never cached on the model.** A recipe is
mutable while it is being resolved -- ``adjust.apply_adjustments`` inserts steps
and renumbers every position after them -- so an index hanging off ``Recipe`` or
memoised on ``Resolution`` would be silently stale for exactly the documents that
need it most, and would read as a data bug rather than a caching one. Building it
is one pass over the steps: do it in the function that needs it, from the
*effective* document, and pass it down.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Mapping, Union

from .model import ComponentUse, Ingredient, Portion, Product, Recipe, Step, fragment
from .resolve import effective_recipe

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .resolve import Resolution

#: The three id namespaces a ``rw:consumes`` may point into.
INGREDIENT = "ingredient"
COMPONENT = "component"
PRODUCT = "product"


@dataclass(frozen=True, slots=True)
class Node:
    """One thing in the graph, whichever namespace it came from.

    ``kind`` matters because the three are not interchangeable to a caller: an
    ingredient row has a mass, a component use has a sub-recipe behind it, and an
    intermediate has neither -- "half the brownie batter" has no weight and no
    document. ``label`` is what the cook is shown, and each kind falls back
    differently on purpose: an ingredient and a component are shown under the
    name the document gave them even when that is empty, while an intermediate
    falls back to its id, because ``#brownie-batter`` still reads as something.
    """

    id: str
    kind: str
    label: str
    source: Ingredient | ComponentUse | Product

    @property
    def is_ingredient(self) -> bool:
        return self.kind == INGREDIENT

    @property
    def is_component(self) -> bool:
        return self.kind == COMPONENT

    @property
    def is_product(self) -> bool:
        return self.kind == PRODUCT


@dataclass(frozen=True, slots=True)
class Use:
    """One step's use of one thing, and how much of it that step takes.

    ``ref`` is the reference *as the step wrote it*, which is what the validator
    has to quote back at an author. The share is a ``Portion`` and stays one:
    portions are display-only and never resolved to a mass (``docs/format.md``
    § Portions).
    """

    step: Step
    ref: str
    portion: Portion


@dataclass(frozen=True, slots=True)
class Input:
    """One *resolved* thing a step consumes: what it is, and this step's share."""

    node: Node
    portion: Portion

    @property
    def ref(self) -> str:
        """The node's own id, not the spelling the step used.

        Deliberate. A caller that goes on to look a mass up by this id -- which
        is what ``cookalong.step_ingredients`` does against
        ``resolution.ingredients`` -- has to be handed the id the row is filed
        under, or a step writing ``urn:recipe:x#flour`` against an ingredient
        called ``#flour`` renders the right name and no weight at all.
        """
        return self.node.id

    @property
    def label(self) -> str:
        return self.node.label


class RecipeGraph:
    """Every question the five walkers used to ask by walking.

    Eager: everything is built in one pass over the steps, because every caller
    that builds one needs at least two of the indexes and the whole thing is
    cheaper than the ``dependencies()`` call it replaces.
    """

    __slots__ = (
        "recipe",
        "ordered_steps",
        "edges",
        "dependencies",
        "successors",
        "_nodes",
        "_steps",
        "_steps_view",
        "_producer",
        "_product_ids",
        "_consumed_ids",
        "_consumers",
        "_consumers_view",
        "_first_use",
        "_first_use_view",
    )

    def __init__(self, recipe: Recipe) -> None:
        self.recipe = recipe

        #: Steps in display order. The renderer's blocking and the cook-along
        #: both walk this; ``recipe.steps`` is document order, and the reader
        #: assigns positions from it when a document omits them, so the two
        #: normally coincide -- but ``rw:position`` is what the table prints.
        self.ordered_steps: tuple[Step, ...] = tuple(
            sorted(recipe.steps, key=lambda s: s.position)
        )
        self._steps: dict[str, Step] = {step.id: step for step in recipe.steps}
        self._steps_view: Mapping[str, Step] = MappingProxyType(self._steps)

        # Products first, so an ingredient row or a component use of the same id
        # outranks an intermediate -- the precedence
        # ``render.ingredients_for_step`` has always applied by testing
        # ingredient, then component, then product. Within the products a later
        # step wins, which is what both of the old maps did.
        products: dict[str, Product] = {}
        producer: dict[str, Step] = {}
        for step in recipe.steps:
            for product in step.produces:
                products[product.id] = product
                producer[product.id] = step
        self._producer = producer
        self._product_ids = frozenset(products)

        nodes: dict[str, Node] = {}
        for product_id, product in products.items():
            nodes[product_id] = Node(
                product_id, PRODUCT, product.name or product_id, product
            )
        for comp in recipe.components:
            nodes[comp.id] = Node(comp.id, COMPONENT, comp.label, comp)
        for ing in recipe.ingredients:
            nodes[ing.id] = Node(ing.id, INGREDIENT, ing.name, ing)
        self._nodes = nodes

        consumers: dict[str, list[Use]] = {}
        first_use: dict[str, Step] = {}
        edges: list[Use] = []
        for step in self.ordered_steps:
            for consumed in step.consumes:
                use = Use(step, consumed.ref, consumed.portion)
                edges.append(use)
                # Filed under the node's id where the reference resolves, so two
                # spellings of one target are one target: the portion rules in
                # ``validate`` add fractions up per target, and grouping them by
                # spelling would let a document take 90% of a thing twice.
                key = self.canonical(consumed.ref)
                consumers.setdefault(key, []).append(use)
                first_use.setdefault(key, step)
        self.edges: tuple[Use, ...] = tuple(edges)
        self._consumers = consumers
        self._consumed_ids = frozenset(consumers)
        self._consumers_view: Mapping[str, list[Use]] = MappingProxyType(consumers)
        self._first_use = first_use
        self._first_use_view: Mapping[str, Step] = MappingProxyType(first_use)

        self.dependencies: dict[str, set[str]] = self._build_dependencies()
        self.successors: dict[str, set[str]] = self._invert(self.dependencies)

    # -- lookup ------------------------------------------------------------

    def node(self, ref: str) -> Node | None:
        """The thing ``ref`` names, across all three id namespaces.

        The one tolerance rule, applied once: the reference as written, then its
        fragment. Nothing tries the other direction -- a query of ``#flour``
        does not reach a node stored as ``urn:recipe:x#flour`` -- because that is
        the rule ``Recipe.ingredient()`` has always had and widening it here
        would change which document a bare fragment can address.
        """
        found = self._nodes.get(ref)
        if found is not None:
            return found
        return self._nodes.get(fragment(ref))

    def canonical(self, ref: str) -> str:
        """The id this graph files ``ref`` under: the node's own, if it resolves.

        A reference that names nothing keeps its own spelling, so a dangling
        ``rw:consumes`` is still reported in the words the author wrote.
        """
        found = self.node(ref)
        return ref if found is None else found.id

    def label(self, ref: str) -> str:
        """What to show the cook for ``ref``, falling back on the reference."""
        found = self.node(ref)
        return ref if found is None else found.label

    def ingredient(self, ref: str) -> Ingredient | None:
        found = self.node(ref)
        return found.source if found is not None and found.is_ingredient else None  # type: ignore[return-value]

    def component(self, ref: str) -> ComponentUse | None:
        found = self.node(ref)
        return found.source if found is not None and found.is_component else None  # type: ignore[return-value]

    def product(self, ref: str) -> Product | None:
        found = self.node(ref)
        return found.source if found is not None and found.is_product else None  # type: ignore[return-value]

    def step(self, ref: str) -> Step | None:
        """A step by id, under the same tolerance rule as everything else."""
        found = self._steps.get(ref)
        if found is not None:
            return found
        return self._steps.get(fragment(ref))

    def step_id(self, ref: str) -> str | None:
        """The literal id of the step ``ref`` names, or ``None`` for no such step.

        What a caller wants when the reference is about to be used as a *key*.
        Every scheduling property names a step -- ``rw:maxDelayAfter``'s
        ``rw:from``, ``rw:minDelayAfter``'s, ``rw:leadBefore``'s ``rw:step`` --
        and the planner indexes its start and end times by the step's own id, so
        a target written the long way has to be resolved before it is looked up
        or the constraint is silently dropped. That is not hypothetical: it is
        how a fully-qualified ``rw:from`` lost three hours of chilling.
        """
        found = self.step(ref)
        return None if found is None else found.id

    @property
    def steps_by_id(self) -> Mapping[str, Step]:
        """Every step by its literal id -- the index four callers rebuilt."""
        return self._steps_view

    # -- edges -------------------------------------------------------------

    def producer(self, ref: str) -> Step | None:
        """The step that emits ``ref``, or ``None`` if nothing does.

        One answer where there used to be three. The planner wanted the step id,
        the renderer wanted the label, and the validator only ever wanted to know
        whether an id existed at all; all three are this, plus an attribute.
        """
        found = self._producer.get(ref)
        if found is not None:
            return found
        return self._producer.get(fragment(ref))

    def consumers(self, ref: str) -> list[Use]:
        """Every step that takes some of ``ref``, with how much, in step order."""
        return list(self._consumers.get(self.canonical(ref), ()))

    @property
    def consumers_by_ref(self) -> Mapping[str, list[Use]]:
        """Uses grouped by target, in the order the cook first meets each one."""
        return self._consumers_view

    def first_use(self, ref: str) -> Step | None:
        """The earliest step consuming ``ref``.

        The whole of the Modernist row-blocking rule: an ingredient's block is
        decided by the first step that consumes it. Returning the *step* rather
        than its position number is what stops two things first used by two
        different steps that happen to share a ``position`` from collapsing into
        one block.
        """
        return self._first_use.get(self.canonical(ref))

    @property
    def first_use_steps(self) -> Mapping[str, Step]:
        return self._first_use_view

    def step_inputs(self, step_id: str) -> list[Input]:
        """What to put in front of the cook at one step: each thing, and its share.

        A reference that resolves to nothing is dropped rather than guessed at.
        The validator reports it as ``dangling-consume``; the cook-along must not
        invent a row for it.
        """
        step = self.step(step_id)
        if step is None:
            return []
        out: list[Input] = []
        for consumed in step.consumes:
            found = self.node(consumed.ref)
            if found is not None:
                out.append(Input(found, consumed.portion))
        return out

    # -- shape -------------------------------------------------------------

    @property
    def product_ids(self) -> frozenset[str]:
        """Every id any step claims to produce."""
        return self._product_ids

    @property
    def consumed_ids(self) -> frozenset[str]:
        """Every id any step consumes, canonicalised.

        Canonical rather than as-written, which is the fix for two rules at once:
        a component consumed under its full ``@id`` is no longer reported as
        never used, and ``unconsumed_products`` no longer calls a product
        terminal because the step that takes it spelled the reference out.
        """
        return self._consumed_ids

    @property
    def last_position(self) -> int:
        """The highest ``rw:position`` in the document.

        One of three separate notions of "the end", deliberately kept apart --
        see ``unconsumed_products`` and ``sink_steps``. This one is about the
        *page*: the validator excuses the last step on the page from needing a
        dependant, because the thing at the bottom of a recipe is allowed to be
        the thing you eat.
        """
        return max((step.position for step in self.recipe.steps), default=0)

    def unconsumed_products(self) -> set[str]:
        """Products nothing takes -- the graph's sinks, counted by *product*.

        A different question from ``last_position`` and from ``sink_steps``, and
        they coincide on today's corpus only by accident. A recipe that finishes
        two things at once (a curry and the rice beside it) has two unconsumed
        products and one last position; a recipe whose final step is a plating
        instruction that produces nothing has a last position and no unconsumed
        products at all.
        """
        return set(self._product_ids - self.consumed_ids)

    def sink_steps(self) -> list[Step]:
        """Steps that take something and emit nothing.

        The third notion of "the end", and the one that keeps
        ``no-terminal-product`` from firing on a perfectly good recipe whose last
        instruction is *"serve"*.
        """
        return [s for s in self.recipe.steps if not s.produces and s.consumes]

    # -- dependency edges --------------------------------------------------

    def _build_dependencies(self) -> dict[str, set[str]]:
        """Which steps each step waits on.

        Three sources, as ``docs/format.md`` § Scheduling has them: consuming
        another step's product, an explicit ``rw:maxDelayAfter`` or
        ``rw:minDelayAfter``, and an explicit ``rw:leadBefore``. All three now go
        through the tolerant lookups, which is the half of the asymmetry bug that
        lived in the planner: this used to match a constraint's target by exact
        dict key while ``_edge_gap`` matched the same target through
        ``recipe.step()``, so a fully-qualified ``rw:from`` produced no edge and a
        mandatory wait on an edge that did not exist.
        """
        deps: dict[str, set[str]] = {step.id: set() for step in self.recipe.steps}
        for step in self.recipe.steps:
            for consumed in step.consumes:
                emitter = self.producer(consumed.ref)
                if emitter is not None and emitter.id != step.id:
                    deps[step.id].add(emitter.id)
            for constraint in (*step.max_delay_after, *step.min_delay_after):
                other = self.step_id(constraint.from_step)
                if other is not None:
                    deps[step.id].add(other)
            for lead_step in step.lead_before:
                other = self.step_id(lead_step)
                if other is not None:
                    deps[step.id].add(other)
        return deps

    @staticmethod
    def _invert(deps: dict[str, set[str]]) -> dict[str, set[str]]:
        out: dict[str, set[str]] = {step_id: set() for step_id in deps}
        for step_id, needs in deps.items():
            for need in needs:
                out.setdefault(need, set()).add(step_id)
        return out


#: What every graph query will accept: a bare document, a resolution, or a graph
#: somebody already built.
GraphSource = Union[Recipe, "Resolution", RecipeGraph]


def recipe_graph(source: GraphSource) -> RecipeGraph:
    """Index the document a query is actually about.

    Takes exactly what ``schedule()`` and ``render_table()`` take, plus an
    already-built graph -- so a function deep inside a walk can be handed either
    and a caller that already has the index never pays for it twice. The
    ``Resolution`` case goes through ``effective_recipe``, because the coffee
    buttercream's own file is a patch list and indexing *that* answers every
    question with "nothing".
    """
    if isinstance(source, RecipeGraph):
        return source
    return RecipeGraph(effective_recipe(source))
