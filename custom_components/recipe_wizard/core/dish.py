"""The **dish**: a recipe resolved together with its components, recursively.

"Dish" is a new domain term, and it names the thing a cook actually makes. A
``Recipe`` is a document; a ``Resolution`` is one document at one scale; a
``ComponentUse`` is a parent's *use* of a sub-recipe. None of those is the
whole of dinner. ``recipes/vanilla-cake.json`` is not a cake until its
buttercream is resolved alongside it, and until this module existed nothing
resolved the two together: ``resolve()`` never reads ``recipe.components``, and
``resolve_component()`` resolves exactly one use, one level deep. So every
caller walked the tree by hand -- the CLI's ``--components``, the validator's
component checks, and the shopping-list roll-up would have been the third and
fourth. Walk it once, here.

Four things the data forces, none of them optional:

**Scale propagates.** ``resolve_component()`` computes a child's scale from
``use.requires_batches`` alone; it cannot see the parent's scale, because a use
is a property of the document and knows nothing about the batch being made.
Doubling the cake has to double the frosting -- "propagating as a plain
factor", per the format doc -- so the tree multiplies each parent's *effective*
scale into its children's requests. Effective, not requested: if a parent's
batch policy rounds 2.25 eggs up and renormalises to x2.05, the frosting
follows the batch that is really being made, not the one that was asked for.

**A citation is recorded, not raised.** Modernist's *"see page 121"* and
RecipeTin's cookbook-only flavours are referenced, renderable and not
expandable. ``resolve_component()`` rightly raises ``UnresolvableComponent``;
a dish catches exactly that one exception and files the use under
``unresolvable``, because the cook still has to be told to go and get it, and
the shopping list has to know to leave it off. Every other exception -- a
missing ``@id``, a patch against a target that does not exist, a batch below
the minimum -- still propagates.

**Optional components stay optional.** The coffee cake's glaze and the qeema's
mint yogurt (``recipes/qeema.json``) are take-it-or-leave-it as *whole
components*, so the flag has to survive onto the node and ``walk()`` has to be
able to leave those subtrees out.

**Recursion terminates.** The corpus is two levels deep today and a component
cycle is not expressible in any recipe anyone has written -- which is exactly
why it is worth guarding before someone writes one. ``ComponentCycleError``
names the path, the same way ``Library.variant_chain`` refuses a variant cycle
rather than hanging.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Iterator

from .library import Library, LibraryError
from .model import Adjustment, ComponentUse
from .resolve import (
    Resolution,
    UnresolvableComponent,
    materialise,
    resolve,
    resolve_component,
)
from .units import Quantity


class ComponentCycleError(LibraryError):
    """A recipe reaches itself through its components.

    A ``LibraryError`` because it is a bad reference between documents, which
    also means the validator's existing component handling reports it rather
    than crashing on it.
    """


@dataclass(slots=True)
class Dish:
    """A resolved recipe and its resolved components, in source order.

    ``label`` is the *use's* label for a component ("Vanilla buttercream" as
    the cake calls it) and the recipe's name at the root, because that is what
    the cook is reading on this page.
    """

    resolution: Resolution
    label: str
    components: list["Dish"] = field(default_factory=list)
    unresolvable: list[ComponentUse] = field(default_factory=list)
    """Uses that could not be expanded: a book citation, or a use with no
    recipe at all. Format ``UnresolvableComponent(use)`` for the message."""
    optional: bool = False
    use: ComponentUse | None = None
    """The use that pulled this dish in; ``None`` at the root. Carries the
    things that belong to the use rather than the recipe -- the presentation
    mode, the local overrides, the note -- so a caller rendering the tree does
    not have to go back to the parent document to find them."""

    def walk(self, *, include_optional: bool = True) -> Iterator["Dish"]:
        """This dish, then its descendants, depth-first in source order.

        With ``include_optional=False`` an optional component and everything
        under it is skipped, which is how a caller folds the tree "without the
        mint yogurt" without having to know the shape of the tree. The root is
        always yielded.
        """
        yield self
        for child in self.components:
            if child.optional and not include_optional:
                continue
            yield from child.walk(include_optional=include_optional)

    def all_warnings(self, *, include_optional: bool = True) -> list[tuple[str, str]]:
        """Every warning in the tree, paired with the label that produced it.

        Kept as pairs rather than concatenated: "the tins will not hold it" is
        about the cake and "rounded up to 1 whole batch" is about the frosting,
        and a cook who cannot tell which is which is worse off than one who
        sees only the parent's.
        """
        return [
            (dish.label, warning)
            for dish in self.walk(include_optional=include_optional)
            for warning in dish.resolution.warnings
        ]

    def all_change_log(self, *, include_optional: bool = True) -> list[tuple[str, str]]:
        """Every change-log entry in the tree, labelled the same way.

        The cake's local "make the butter 225 g" override is recorded against
        the *frosting's* resolution, so it is only findable this way.
        """
        return [
            (dish.label, entry)
            for dish in self.walk(include_optional=include_optional)
            for entry in dish.resolution.change_log
        ]


def resolve_dish(
    library: Library,
    recipe_id: str,
    *,
    batches: float = 1.0,
    requires_mass: Quantity | None = None,
    adjustments: list[Adjustment] | None = None,
    strict: bool = False,
) -> Dish:
    """Resolve a recipe and everything it is made of.

    ``strict`` defaults to ``False`` where ``resolve()`` defaults to ``True``:
    a dish is built to be shown, and one component that lands below its
    minimum batch should degrade to a warning on that component rather than
    cost the cook the whole tree. Pass ``strict=True`` to refuse instead.
    """
    resolution = resolve(
        library,
        recipe_id,
        requires_mass=requires_mass,
        requires_batches=batches,
        adjustments=adjustments,
        strict=strict,
    )
    return _grow(
        library,
        recipe_id,
        resolution,
        use=None,
        adjustments=adjustments,
        strict=strict,
        path=(recipe_id,),
    )


def _grow(
    library: Library,
    recipe_id: str,
    resolution: Resolution,
    *,
    use: ComponentUse | None,
    adjustments: list[Adjustment] | None,
    strict: bool,
    path: tuple[str, ...],
) -> Dish:
    """Attach the children of an already-resolved recipe, recursively."""
    dish = Dish(
        resolution=resolution,
        label=resolution.label,
        optional=bool(use.optional) if use is not None else False,
        use=use,
    )

    for child_use in _components_of(library, recipe_id, adjustments):
        ref = child_use.recipe_ref
        if ref is not None and ref in path:
            raise ComponentCycleError(
                f"component cycle through {ref!r}: " + " -> ".join([*path, ref])
            )
        try:
            child = resolve_component(
                library, _scaled_use(child_use, resolution.scale), strict=strict
            )
        except UnresolvableComponent:
            # Cited, or no recipe to expand. Recorded so it still renders and
            # so the shopping list can exclude it deliberately.
            dish.unresolvable.append(child_use)
            continue
        assert ref is not None  # resolve_component raises without one
        dish.components.append(
            _grow(
                library,
                ref,
                child,
                use=child_use,
                adjustments=child_use.adjustments,
                strict=strict,
                path=(*path, ref),
            )
        )

    return dish


def _components_of(
    library: Library, recipe_id: str, adjustments: list[Adjustment] | None
) -> list[ComponentUse]:
    """The components of the *effective* recipe, not of the document on disk.

    ``materialise()`` again rather than ``library.recipe()`` because a variant
    inherits its base's components and never restates them: read the document
    directly and a variant of the cake silently loses its frosting.
    ``resolve()`` does this work too but does not hand back the recipe, so the
    uses here are deep copies of the library's -- compare them by ``id``, not
    by identity.
    """
    recipe, _ = materialise(library, recipe_id, adjustments=adjustments)
    return recipe.components


def _scaled_use(use: ComponentUse, factor: float) -> ComponentUse:
    """The same use, asked for ``factor`` times over.

    A copy, because the use belongs to the document: mutating it would make
    the second person to resolve the cake at x2 get x4. A mass request scales
    as a mass; everything else is a batch count, which is what parents
    overwhelmingly write ("frost between the layers" is one batch of frosting,
    at any cake size).
    """
    if abs(factor - 1.0) < 1e-9:
        return use
    if use.requires_mass is not None:
        return replace(use, requires_mass=use.requires_mass.scaled(factor))
    return replace(use, requires_batches=use.requires_batches * factor)
