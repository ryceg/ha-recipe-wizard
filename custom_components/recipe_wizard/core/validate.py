"""Validation. Cheap checks that catch most authoring errors.

Two things shape this module.

First, the important checks run against the *base* as well as the variant, so
deleting ``#vanilla`` from a base recipe fails when you save the base -- not
months later when something tries to resolve a variant that patched it.

Second, findings are gated on ``enrichment_level``. Recipes arrive scraped
(level 0: ingredient strings and step text, nothing linked) and are lifted
towards level 3 by an enrichment skill. Firing level-3 rules at a level-0
document buries the real findings under noise about a document that was never
claiming to be more than a scrape -- and makes the validator useless as the
skill's success signal, which is the job it actually has to do.
"""

from __future__ import annotations

from dataclasses import dataclass

from .adjust import AdjustmentError
from .library import Library, LibraryError
from .mass import FORM_UNKNOWN, mass_table
from .model import Recipe
from .resolve import (
    BatchConstraintError,
    UnresolvableComponent,
    materialise,
    resolve_component,
)
from .schedule import (
    ScheduleError,
    dependencies,
    successors,
    topological_order,
)

ERROR = "error"
WARNING = "warning"
INFO = "info"

#: Fractions of one thing may sum slightly over 1 -- "just over half" twice is
#: how sources actually write it -- but not by much.
PORTION_TOLERANCE = 0.1

#: An ingredient below this share of the batch is too small for a density
#: quibble to matter. Findings should be proportional to their consequence.
#:
#: "The batch" is the resolver's non-optional input total and nothing else.
#: This used to be measured against a local sum that counted the optional milk
#: and ignored the mass loss factor, so the denominator was a quantity no other
#: part of the system called a yield, and a threshold tuned against it was
#: tuned against a number that did not mean anything.
NEGLIGIBLE_SHARE = 0.01


@dataclass(slots=True)
class Finding:
    level: str
    code: str
    where: str
    message: str

    def __str__(self) -> str:
        return f"[{self.level:7}] {self.where}: {self.message}"


def _known_ids(recipe: Recipe) -> set[str]:
    ids = {ing.id for ing in recipe.ingredients}
    ids |= {comp.id for comp in recipe.components}
    for step in recipe.steps:
        ids |= {product.id for product in step.produces}
    return ids


def validate_recipe(recipe: Recipe, library: Library) -> list[Finding]:
    """Every check that can be run against a single recipe document."""
    findings: list[Finding] = []
    where = recipe.id or recipe.name
    level = recipe.enrichment_level

    def add(severity: str, code: str, message: str) -> None:
        findings.append(Finding(severity, code, where, message))

    # -- Always ---------------------------------------------------------
    try:
        materialise(library, recipe.id)
    except AdjustmentError as exc:
        add(ERROR, "unresolvable-patch", str(exc))
    except LibraryError as exc:
        add(ERROR, "bad-reference", str(exc))

    # A variant is a patch list and legitimately declares nothing of its own.
    if not recipe.ingredients and not recipe.components and not recipe.is_variant_of:
        add(WARNING, "no-ingredients",
            "the document has neither rw:ingredients nor recipeIngredient")

    # -- Level 1: quantities exist --------------------------------------
    if level >= 1:
        masses = mass_table(recipe, library.foods)
        batch = masses.input_total_g

        for ing in recipe.ingredients:
            result = masses.result(ing.id)
            for warning in result.warnings:
                if "disagree" in warning:
                    add(WARNING, "unit-divergence", warning)
                else:
                    add(INFO, "unresolved-mass", warning)

            # A shaky density only matters if the ingredient is a meaningful
            # part of the batch. Nobody weighs 1 1/4 tsp of cumin, and being
            # 30% out on 2.6 g of a 900 g curry changes nothing -- reporting it
            # buries the findings that do matter.
            share = (result.grams or 0.0) / batch if batch else 0.0
            if share < NEGLIGIBLE_SHARE:
                continue

            # Why the mass is doubtful was decided when it was computed. Asking
            # the result beats re-fetching the Food and re-reading
            # form_sensitive off it, which is how this block came to hold a
            # second, drifting copy of mass.py's reasoning.
            if result.confidence == "low" and result.source == "volume":
                if result.reason == FORM_UNKNOWN:
                    add(INFO, "missing-form",
                        f"{ing.name!r} is measured by volume and its density "
                        "depends on the cut or pack; give rw:form or a mass")
                else:
                    add(INFO, "low-confidence-density",
                        f"{ing.name!r} is measured by volume and its density is "
                        "not well known; prefer a mass here")

    # -- Level 2: ingredients linked to steps ---------------------------
    if level >= 2:
        for step in recipe.steps:
            if step.id.lstrip("#").startswith("step-"):
                add(WARNING, "positional-step-id",
                    f"{step.id!r} is positional; patches targeting it break when a "
                    "step is inserted above. Use a semantic id.")

        known = _known_ids(recipe)
        consumed: set[str] = set()
        for step in recipe.steps:
            for ref in step.consumed_ids:
                consumed.add(ref)
                if ref not in known:
                    add(ERROR, "dangling-consume",
                        f"{step.id} consumes {ref!r}, which is not an ingredient, "
                        "a component, or produced by any step")

        for ing in recipe.ingredients:
            if ing.id not in consumed:
                add(WARNING, "unused-ingredient",
                    f"{ing.name!r} ({ing.id}) is never consumed by any step")

        findings.extend(_portion_findings(recipe, where))

        # A step nothing depends on floats free. Under backward scheduling it
        # lands at the end of the plan, which is how a recipe ends up
        # preheating its oven after the bake.
        depended_on = successors(dependencies(recipe))
        last = max((s.position for s in recipe.steps), default=0)
        for step in recipe.steps:
            if depended_on.get(step.id) or step.position == last:
                continue
            add(WARNING, "dangling-step",
                f"nothing depends on {step.id}, so it has no place in the plan "
                "and will be scheduled arbitrarily; give it a rw:produces that "
                "something consumes, or a rw:leadBefore on the step that needs it")

        try:
            topological_order(recipe)
        except ScheduleError as exc:
            add(ERROR, "step-cycle", str(exc))

    # -- Level 3: components and a full graph ---------------------------
    if level >= 3:
        consumed = {ref for step in recipe.steps for ref in step.consumed_ids}
        for comp in recipe.components:
            if comp.id not in consumed:
                add(WARNING, "unused-component",
                    f"component {comp.label!r} ({comp.id}) is never consumed by "
                    "any step")

        produced = {p.id for step in recipe.steps for p in step.produces}
        terminal = produced - consumed
        sinks = [s for s in recipe.steps if not s.produces and s.consumes]
        if recipe.steps and not terminal and not sinks:
            add(ERROR, "no-terminal-product", "no step produces a final result")
        elif len(terminal) > 1:
            add(WARNING, "multiple-terminal-products",
                "more than one product is never consumed: "
                + ", ".join(sorted(terminal)))

        findings.extend(_component_findings(recipe, library, where))

    return findings


def _portion_findings(recipe: Recipe, where: str) -> list[Finding]:
    """Portions of one thing must add up to something a cook could do."""
    findings: list[Finding] = []
    by_target: dict[str, list] = {}
    for step in recipe.steps:
        for consumed in step.consumes:
            by_target.setdefault(consumed.ref, []).append((step, consumed.portion))

    for ref, uses in by_target.items():
        portions = [p for _, p in uses]
        remainders = [p for p in portions if p.remainder]
        if len(remainders) > 1:
            findings.append(Finding(
                ERROR, "multiple-remainders", where,
                f"{ref} is claimed as 'the rest' by {len(remainders)} steps; only "
                "one step can take the remainder"))

        fractions = [p.fraction for p in portions if p.fraction is not None]
        if fractions:
            total = sum(fractions)
            if total > 1 + PORTION_TOLERANCE:
                findings.append(Finding(
                    ERROR, "portions-exceed-whole", where,
                    f"steps take {total:.0%} of {ref} between them"))
            elif total < 1 - PORTION_TOLERANCE and not remainders:
                findings.append(Finding(
                    WARNING, "portions-under-whole", where,
                    f"steps account for only {total:.0%} of {ref}, and no step "
                    "takes the remainder - is a use missing?"))

        wholes = [p for p in portions if p.is_whole]
        if wholes and len(uses) > 1:
            findings.append(Finding(
                WARNING, "unportioned-multiple-use", where,
                f"{ref} is used by {len(uses)} steps but {len(wholes)} of them "
                "claim all of it; add rw:portion"))
    return findings


def _component_findings(
    recipe: Recipe, library: Library, where: str
) -> list[Finding]:
    findings: list[Finding] = []

    def add(severity: str, code: str, message: str) -> None:
        findings.append(Finding(severity, code, where, message))

    for comp in recipe.components:
        if comp.recipe_ref and comp.recipe_ref not in library.recipes:
            if comp.citation:
                add(INFO, "cited-component",
                    f"{comp.label!r} is a citation, not a document: not expandable "
                    "and excluded from shopping lists")
            else:
                add(ERROR, "missing-component",
                    f"{comp.label!r} references {comp.recipe_ref!r}, which is not "
                    "in the library")
            continue
        try:
            resolution = resolve_component(library, comp)
        except UnresolvableComponent:
            add(INFO, "cited-component",
                f"{comp.label!r} is cited but not resolvable")
            continue
        except BatchConstraintError as exc:
            add(ERROR, "batch-constraint", str(exc))
            continue
        except (AdjustmentError, LibraryError) as exc:
            add(ERROR, "component-error", str(exc))
            continue

        for warning in resolution.warnings:
            add(WARNING, "component-warning", f"{comp.label}: {warning}")

        # Storage conflicts. An overlap on one method does not clear the
        # conflict: the buttercream says refrigerate and the cake says do not,
        # and they agree only about the freezer.
        parent_methods = {s.method for s in recipe.storage}
        divergent = {s.method for s in resolution.storage} - parent_methods
        if parent_methods and divergent:
            severity = INFO if recipe.storage_overrides_components else WARNING
            add(severity, "storage-conflict",
                f"{comp.label!r} can be stored {'/'.join(sorted(divergent))}, which "
                f"the parent does not list (parent: "
                f"{'/'.join(sorted(parent_methods))})"
                + (" - parent declared authoritative"
                   if recipe.storage_overrides_components
                   else "; declare rw:storageOverridesComponents to resolve"))
    return findings


def validate_library(library: Library) -> list[Finding]:
    """Validate every recipe, plus cross-document checks."""
    findings: list[Finding] = []
    for recipe in library:
        findings.extend(validate_recipe(recipe, library))

    for family_id, family in library.families.items():
        for member in family.members:
            if member not in library.recipes:
                findings.append(Finding(
                    ERROR, "missing-family-member", family_id,
                    f"member {member!r} is not in the library"))
        if family.default and family.default not in library.recipes:
            findings.append(Finding(
                ERROR, "missing-family-default", family_id,
                f"default {family.default!r} is not in the library"))

    for recipe in library:
        try:
            chain = library.variant_chain(recipe.id)
        except LibraryError as exc:
            findings.append(Finding(ERROR, "variant-cycle", recipe.id, str(exc)))
            continue
        if len(chain) > 2:
            findings.append(Finding(
                WARNING, "deep-variant-chain", recipe.id,
                "variant chains deeper than one level make patch order hard to "
                "reason about: " + " -> ".join(r.id for r in chain)))
    return findings
