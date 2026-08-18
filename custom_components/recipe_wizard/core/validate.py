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

Every graph rule asks ``graph.py`` rather than walking. That is not only about
the four indexes this module used to rebuild: "known id" was a set of *literal*
``@id`` strings, so a step naming its own frosting
``urn:recipe:rte/vanilla-cake#frosting`` -- legal, since identity lives in
``@id`` -- was reported as ``dangling-consume``. A rule that fires spuriously is
worse than a rule that does not exist.

``Finding`` is the whole of that contract, and it is the only shape in it.
``schedule.py`` used to carry a second, parallel record -- ``Violation(kind,
step_id, message)`` -- which was structurally the same idea and was the one that
named a *node*, and nothing converted between them, so a scheduling defect could
not appear in a validation report at all. It is one record now, produced by both
modules and printed by one function.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Iterable

from .adjust import AdjustmentError
from .graph import RecipeGraph, recipe_graph
from .library import Library, LibraryError
from .mass import FORM_UNKNOWN, mass_table
from .model import Recipe
from .resolve import (
    BatchConstraintError,
    UnresolvableComponent,
    materialise,
    resolve_component,
)
from .schedule import ScheduleError, check_plan, schedule, topological_order

ERROR = "error"
WARNING = "warning"
INFO = "info"

#: The severities, most serious first. This ordering *is* the roll-up, and the
#: roll-up is an exit code -- see ``worst_level``.
SEVERITIES = (ERROR, WARNING, INFO)

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


@dataclass(frozen=True, slots=True)
class Finding:
    """One defect, and the node a fix to it would be applied to.

    ``node`` is why this record exists in this shape. The library is being lifted
    from level 0 by an enrichment skill iterating against this module, so a
    finding is read by an agent before it is read by a person -- and until this
    field existed, the only thing that named the node was the English message.
    The brownies report *"steps account for only 50% of #salt-flakes"*, and a
    skill that wanted to fix that one ingredient row had to parse the sentence to
    find out which of the document's ten rows to edit -- two of which are salt.

    It holds a step id, an ingredient id, a component id, or ``None``, and always
    as ``graph.py`` files it: ``RecipeGraph.canonical`` for a consumed target, the
    node's own ``@id`` everywhere else. So the id is canonical under the library's
    one lookup rule and a caller can hand it straight back to ``RecipeGraph.node``
    or ``RecipeGraph.step`` and get the thing. ``None`` means the finding really
    is about the whole document -- a variant cycle, or a recipe no step produces a
    result for, have no single node to point at, and inventing one would send a
    fixer at the wrong place.

    ``recipe`` is the document the finding is about. Usually a recipe's ``@id``;
    for the two cross-document rules in ``validate_library`` it is the *family's*,
    because the family is the document that is wrong and the member it names goes
    in ``node``.
    """

    level: str
    code: str
    recipe: str
    message: str
    node: str | None = None

    def __str__(self) -> str:
        """One readable line for a human reading ``--validate``.

        The node is printed and not merely carried. The same line is what the
        enrichment skill reads off stdout, and a person diagnosing the brownies'
        salt wants to see ``#salt-flakes`` without re-reading the sentence to
        find it.
        """
        subject = self.recipe if self.node is None else f"{self.recipe} {self.node}"
        return f"[{self.level:7}] {subject}: {self.message}"


def worst_level(findings: Iterable[Finding]) -> str | None:
    """The most serious level present, or ``None`` for a clean report.

    Reintroduced with a caller rather than because it used to exist: ``__main__``
    turns it into the process exit status, so the enrichment skill's loop can ask
    "are there errors yet" with the exit code of ``python -m recipe_wizard <slug>
    --validate`` instead of scraping the printed count back out of stdout.
    ``docs/format.md`` § Scope: the validator is the contract, and an agent
    iterating against a contract has to be able to put a yes/no question to it.
    """
    present = {finding.level for finding in findings}
    for level in SEVERITIES:
        if level in present:
            return level
    return None


def validate_recipe(recipe: Recipe, library: Library) -> list[Finding]:
    """Every check that can be run against a single recipe document."""
    findings: list[Finding] = []
    where = recipe.id or recipe.name
    level = recipe.enrichment_level
    # One index for every graph rule below. This module used to build the set of
    # known ids twice, the dependency map and its inverse from scratch, and the
    # per-target portion grouping by walking every step again.
    graph = recipe_graph(recipe)

    def add(severity: str, code: str, message: str, node: str | None = None) -> None:
        findings.append(Finding(severity, code, where, message, node))

    def adopt(produced: Iterable[Finding]) -> None:
        """Take findings another module made about *this* document.

        Only ``recipe`` is rewritten, and only because ``where`` falls back to the
        name for a document with no ``@id`` -- a producer given the id has no way
        to know that. The level, the code and the node are the producer's and are
        left exactly as they were: re-deciding any of them here is what this
        conversion exists to stop.
        """
        findings.extend(replace(finding, recipe=where) for finding in produced)

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
            # Already findings, already levelled, already naming this line. This
            # loop used to build them here from bare strings, and it decided
            # which was a divergence by looking for the word "disagree" in the
            # message -- so the severity of a finding hung on the wording of a
            # sentence written in another module, and rewording that sentence
            # would silently reclassify it.
            adopt(result.findings)

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
                        "depends on the cut or pack; give rw:form or a mass",
                        ing.id)
                else:
                    add(INFO, "low-confidence-density",
                        f"{ing.name!r} is measured by volume and its density is "
                        "not well known; prefer a mass here", ing.id)

    # -- Level 2: ingredients linked to steps ---------------------------
    if level >= 2:
        for step in recipe.steps:
            if step.id.lstrip("#").startswith("step-"):
                add(WARNING, "positional-step-id",
                    f"{step.id!r} is positional; patches targeting it break when a "
                    "step is inserted above. Use a semantic id.", step.id)

        # "Known" is now one question with one answer: does the graph hold a node
        # under this reference, in any of the three id namespaces? It used to be
        # a set built here and a second, differently-built set at level 3.
        for use in graph.edges:
            if graph.node(use.ref) is None:
                # The *step* is the node, not the reference: a dangling
                # ``rw:consumes`` names nothing, so there is nothing to look up
                # under it, and the edit that fixes it is made on the step's own
                # consumes list. The reference stays quoted in the message, in the
                # author's own spelling.
                add(ERROR, "dangling-consume",
                    f"{use.step.id} consumes {use.ref!r}, which is not an "
                    "ingredient, a component, or produced by any step",
                    use.step.id)

        consumed = graph.consumed_ids
        for ing in recipe.ingredients:
            if ing.id not in consumed:
                add(WARNING, "unused-ingredient",
                    f"{ing.name!r} ({ing.id}) is never consumed by any step",
                    ing.id)

        findings.extend(_portion_findings(graph, where))

        # A step nothing depends on floats free. Under backward scheduling it
        # lands at the end of the plan, which is how a recipe ends up
        # preheating its oven after the bake.
        #
        # ``last_position`` is "the end" *of the page* -- one of three unrelated
        # notions of the end in this system, and deliberately not merged with the
        # other two. The thing printed at the bottom of a recipe is allowed to be
        # the thing you eat, whatever the dataflow says about it.
        depended_on = graph.successors
        last = graph.last_position
        for step in recipe.steps:
            if depended_on.get(step.id) or step.position == last:
                continue
            add(WARNING, "dangling-step",
                f"nothing depends on {step.id}, so it has no place in the plan "
                "and will be scheduled arbitrarily; give it a rw:produces that "
                "something consumes, or a rw:leadBefore on the step that needs it",
                step.id)

        try:
            topological_order(graph)
        except ScheduleError as exc:
            # No node: a cycle is a property of a *set* of steps, and naming one
            # of them would send a fixer at whichever happened to sort first.
            add(ERROR, "step-cycle", str(exc))
        else:
            findings.extend(_schedule_findings(graph))

    # -- Level 3: components and a full graph ---------------------------
    if level >= 3:
        for comp in recipe.components:
            if comp.id not in graph.consumed_ids:
                add(WARNING, "unused-component",
                    f"component {comp.label!r} ({comp.id}) is never consumed by "
                    "any step", comp.id)

        # The *dataflow* end: products nothing takes, and steps that take
        # something and emit nothing. The third of the three notions of the end,
        # and the only one this rule is about -- a document may have several
        # unconsumed products while having exactly one last page, and the two
        # coincide across today's corpus by accident rather than by rule.
        terminal = graph.unconsumed_products()
        sinks = graph.sink_steps()
        if recipe.steps and not terminal and not sinks:
            add(ERROR, "no-terminal-product", "no step produces a final result")
        elif len(terminal) > 1:
            add(WARNING, "multiple-terminal-products",
                "more than one product is never consumed: "
                + ", ".join(sorted(terminal)))

        findings.extend(_component_findings(recipe, library, where))

    return findings


def _portion_findings(graph: RecipeGraph, where: str) -> list[Finding]:
    """Portions of one thing must add up to something a cook could do.

    Grouped by *target* rather than by the spelling each step used, which the
    graph already does: two steps taking 90% of the same thing under two
    spellings of its id is the exact error this rule exists to catch, and a
    grouping keyed on the raw reference would have reported neither.

    The key of that grouping is also the ``node`` every finding here carries. It
    is ``graph.canonical(ref)``, so the thing named is the id the row is filed
    under and not whichever of two legal spellings the last step happened to use
    -- which is what makes ``#salt-flakes`` something a caller can look up rather
    than a phrase in a sentence.
    """
    findings: list[Finding] = []

    for ref, uses in graph.consumers_by_ref.items():
        portions = [use.portion for use in uses]
        remainders = [p for p in portions if p.remainder]
        if len(remainders) > 1:
            findings.append(Finding(
                ERROR, "multiple-remainders", where,
                f"{ref} is claimed as 'the rest' by {len(remainders)} steps; only "
                "one step can take the remainder", ref))

        fractions = [p.fraction for p in portions if p.fraction is not None]
        if fractions:
            total = sum(fractions)
            if total > 1 + PORTION_TOLERANCE:
                findings.append(Finding(
                    ERROR, "portions-exceed-whole", where,
                    f"steps take {total:.0%} of {ref} between them", ref))
            elif total < 1 - PORTION_TOLERANCE and not remainders:
                findings.append(Finding(
                    WARNING, "portions-under-whole", where,
                    f"steps account for only {total:.0%} of {ref}, and no step "
                    "takes the remainder - is a use missing?", ref))

        wholes = [p for p in portions if p.is_whole]
        if wholes and len(uses) > 1:
            findings.append(Finding(
                WARNING, "unportioned-multiple-use", where,
                f"{ref} is used by {len(uses)} steps but {len(wholes)} of them "
                "claim all of it; add rw:portion", ref))
    return findings


def _schedule_findings(graph: RecipeGraph) -> list[Finding]:
    """Everything only a plan can tell you about a document.

    These checks existed and could not be reached from ``--validate``. The
    planner already reported an unsatisfiable constraint and a ``rw:leadBefore``
    naming no step, and ``check_plan`` already reported every delay a set of
    start times breaks -- and both went out as shapes nothing else in the report
    used, so a recipe whose constraints contradict each other validated clean and
    misbehaved only when somebody thought to ask for a plan.

    Planning a document and then checking it against its own plan is not
    circular. The planner satisfies what it can; ``check_plan`` names what it
    could not, which is exactly the pair of contradictory constraints the "did not
    settle" warning was gesturing at without saying which. Both run against the
    graph this module has already built, so the report and the plan cannot be
    about two different documents -- the mistake ``effective_recipe`` exists to
    prevent, one level up.

    Nothing relabels the findings on the way out: both modules read the recipe id
    off the same graph, so they cannot disagree about which document they are
    about.
    """
    plan = schedule(graph)
    starts = {step.step_id: step.start_s for step in plan.steps}
    return [*plan.findings, *check_plan(graph, starts)]


def _component_findings(
    recipe: Recipe, library: Library, where: str
) -> list[Finding]:
    findings: list[Finding] = []

    # Every finding in here is about one ``rw:ComponentUse``, and the use's own
    # ``@id`` is what a fixer edits -- not the sub-recipe's id, which is a
    # different document and usually not the one that is wrong. The cake's butter
    # override lives on the use; the buttercream on disk is fine.
    def add(severity: str, code: str, message: str, node: str) -> None:
        findings.append(Finding(severity, code, where, message, node))

    for comp in recipe.components:
        if comp.recipe_ref and comp.recipe_ref not in library.recipes:
            if comp.citation:
                add(INFO, "cited-component",
                    f"{comp.label!r} is a citation, not a document: not expandable "
                    "and excluded from shopping lists", comp.id)
            else:
                add(ERROR, "missing-component",
                    f"{comp.label!r} references {comp.recipe_ref!r}, which is not "
                    "in the library", comp.id)
            continue
        try:
            resolution = resolve_component(library, comp)
        except UnresolvableComponent:
            add(INFO, "cited-component",
                f"{comp.label!r} is cited but not resolvable", comp.id)
            continue
        except BatchConstraintError as exc:
            add(ERROR, "batch-constraint", str(exc), comp.id)
            continue
        except (AdjustmentError, LibraryError) as exc:
            add(ERROR, "component-error", str(exc), comp.id)
            continue

        # The child's findings, re-homed onto the use. The code and the level
        # are the resolver's -- a tin that will not hold the frosting is not the
        # same defect as a batch policy with no basis, and this used to flatten
        # both to one ``component-warning`` at ``WARNING``. The *node* is the
        # parent's ``#frosting`` rather than the sub-recipe's own line, per
        # ``docs/format.md``: a finding about a component names the use, because
        # that is the thing in *this* document a fix would be applied to. The
        # sub-recipe's own document reports its own nodes when it is validated.
        for finding in resolution.findings:
            add(finding.level, finding.code,
                f"{comp.label}: {finding.message}", comp.id)

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
                   else "; declare rw:storageOverridesComponents to resolve"),
                comp.id)
    return findings


def validate_library(library: Library) -> list[Finding]:
    """Validate every recipe, plus cross-document checks."""
    findings: list[Finding] = []
    for recipe in library:
        findings.extend(validate_recipe(recipe, library))

    # A family is not a recipe, and these two are the only findings whose subject
    # is not one: the family's own ``@id`` goes in ``recipe`` because the family is
    # the document that is wrong, and the member it names goes in ``node``, because
    # that is the reference an author has to delete or correct.
    for family_id, family in library.families.items():
        for member in family.members:
            if member not in library.recipes:
                findings.append(Finding(
                    ERROR, "missing-family-member", family_id,
                    f"member {member!r} is not in the library", member))
        if family.default and family.default not in library.recipes:
            findings.append(Finding(
                ERROR, "missing-family-default", family_id,
                f"default {family.default!r} is not in the library",
                family.default))

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
