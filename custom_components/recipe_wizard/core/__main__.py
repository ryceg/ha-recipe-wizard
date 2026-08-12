"""Command line entry point: ``python -m recipe_wizard``."""

from __future__ import annotations

import argparse
import json
import sys

from .cookalong import cook_along_from_dish
from .dish import Dish, resolve_dish
from .library import Library
from .render import render_table
from .resolve import UnresolvableComponent
from .schedule import schedule
from .validate import ERROR, WARNING, validate_library, validate_recipe


def _find(library: Library, needle: str):
    if needle in library.recipes:
        return library.recipe(needle)
    matches = [r for r in library if needle.lower() in r.name.lower()
               or needle.lower() in r.id.lower()]
    if not matches:
        raise SystemExit(f"no recipe matching {needle!r}")
    if len(matches) > 1:
        names = "\n  ".join(f"{r.name}  ({r.id})" for r in matches)
        raise SystemExit(f"{needle!r} matches several recipes:\n  {names}")
    return matches[0]


def main(argv: list[str] | None = None) -> int:
    # Recipes are full of accented words and fraction glyphs, and this tool
    # emits JSON that gets redirected to a file. On a cp1252 console that
    # silently writes mojibake, so pin the stream rather than the terminal.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(prog="recipe_wizard")
    parser.add_argument("recipe", nargs="?", help="recipe @id or part of its name")
    parser.add_argument("--list", action="store_true", help="list the library")
    parser.add_argument("--validate", action="store_true", help="report findings")
    parser.add_argument("--plan", action="store_true", help="show the schedule")
    parser.add_argument("--cook", action="store_true",
                        help="the step-by-step cook-along, components grouped")
    parser.add_argument("--components", action="store_true",
                        help="resolve sub-recipes and show their numbers")
    # Doubling is routine, and until this flag existed the table could only ever
    # be rendered at x1 -- which is why nothing noticed that the scaled step
    # portions in ``resolution.steps`` were never read by anything.
    parser.add_argument("--batches", type=float, default=1.0, metavar="N",
                        help="scale to N batches; components follow")
    parser.add_argument("--import", dest="import_from", metavar="URL|FILE",
                        help="import a page's schema.org data as a level-0 document")
    parser.add_argument("--compare", metavar="FILE",
                        help="score an enriched document against a hand-authored one")
    parser.add_argument("--against", metavar="RECIPE",
                        help="the reference recipe for --compare")
    args = parser.parse_args(argv)

    if args.import_from:
        return _import(args.import_from)

    library = Library.load()

    if args.compare:
        return _compare(library, args.compare, args.against)

    if args.list or not args.recipe:
        for recipe in sorted(library, key=lambda r: r.name):
            variant = f"  (variant of {recipe.is_variant_of})" if recipe.is_variant_of else ""
            print(f"{recipe.name:38} {recipe.id}{variant}")
        for family in library.families.values():
            print(f"{family.name:38} {family.id}  [family of {len(family.members)}]")
        if args.validate:
            _report(validate_library(library))
        return 0

    recipe = _find(library, args.recipe)
    # The dish, not the document: a variant's own file may hold nothing but a
    # patch list, and the components have to be resolved with the parent's scale
    # multiplied in rather than one level deep by hand.
    dish = resolve_dish(library, recipe.id, batches=args.batches, strict=False)
    resolution = dish.resolution
    effective = resolution.recipe

    print(f"\n{effective.name.upper()}")
    if effective.url:
        print(effective.url)
    if resolution.batch_yield_g:
        print(f"Yield: {resolution.batch_yield_g:.0f} g "
              f"({effective.yield_basis})")
    if abs(resolution.scale - 1.0) > 1e-9:
        made = f", makes {resolution.produced_g:.0f} g" if resolution.produced_g else ""
        print(f"Batch: x{resolution.scale:g}{made}")
    for entry in effective.storage:
        keeps = entry.keeps.human() if entry.keeps else "unspecified"
        line = f"Storage: {entry.method}, keeps {keeps}"
        if entry.quality_window:
            line += f" (at its best for {entry.quality_window.human()})"
        if entry.condition:
            line += f" - {entry.condition}"
        print(line)
    for method in effective.unsuitable_for:
        print(f"Storage: not suitable for {method}")
    print()
    print(render_table(resolution))
    for warning in resolution.warnings:
        print(f"! {warning}")

    if args.components:
        for index, node in enumerate(dish.walk()):
            for use in node.unresolvable:
                print(f"\n  {use.label}: {UnresolvableComponent(use)}")
            if index == 0:
                continue
            print()
            print(f"  {node.resolution.summary()}")
            for ingredient in node.resolution.ingredients:
                print(f"    {ingredient}")
            for entry in node.resolution.change_log:
                print(f"    . {entry}")
            for warning in node.resolution.warnings:
                print(f"    ! {warning}")

    if args.plan:
        plan = schedule(resolution)
        print(f"\nPLAN  total {plan.total_s / 60:.0f} min | "
              f"hands-on {plan.active_s / 60:.0f} min | "
              f"hands-off {plan.unattended_s / 60:.0f} min")
        for step in plan.steps:
            line = (f"  {step.start_s / 60:6.1f} -> {step.end_s / 60:6.1f}  "
                    f"{step.step_id:22} [{step.attention}]")
            # The clock is an estimate; the state is what decides.
            if step.doneness:
                line += f"  then check: {step.doneness}"
            print(line)
        for chain in plan.rigid_chains:
            print("  no pause allowed: " + " -> ".join(chain))
        for warning in plan.warnings:
            print(f"  ! {warning}")

    if args.cook:
        _cook(dish)

    if args.validate:
        print()
        _report(validate_recipe(recipe, library))

    return 0


def _cook(dish: Dish) -> None:
    """Print the cook-along the Home Assistant view will show, one step a page.

    Components are grouped rather than interleaved, so the frosting arrives as
    its own labelled run of steps with its own plan -- see ``cookalong.py`` for
    why merging the two timelines is a design decision and not a formatting one.
    """
    cook = cook_along_from_dish(dish)
    for entry in cook.sequence():
        step = entry.step
        print(f"\n[{entry.cursor + 1}/{entry.of}] {entry.label} - step {step.position}"
              f"  ({step.attention}, from {step.start_s / 60:.0f} min)")
        print(f"  {step.text}")
        for ingredient in step.ingredients:
            line = f"    - {ingredient.describe()}"
            if ingredient.required_state:
                line += f" [{ingredient.required_state.description}]"
            print(line)
        timer = step.timer_label()
        if timer:
            print(f"    timer: {timer}")
        if step.safety_note:
            print(f"    ! {step.safety_note}")
        if step.may_pause_after:
            print("    you may stop here")


def _import(source: str) -> int:
    """Print a level-0 document for a URL or a saved page."""
    from pathlib import Path

    from .importer import import_page, import_url

    if source.startswith(("http://", "https://")):
        document = import_url(source)
    else:
        document = import_page(Path(source).read_text(encoding="utf-8"))
    print(json.dumps(document, indent=2, ensure_ascii=False))
    return 0


def _compare(library: Library, candidate_path: str, reference_id: str | None) -> int:
    """Score an enriched document against the hand-authored version."""
    from pathlib import Path

    from .compare import compare

    scratch = Library()
    scratch.foods = library.foods
    scratch.add_document(json.loads(Path(candidate_path).read_text(encoding="utf-8")))
    if not scratch.recipes:
        raise SystemExit(f"{candidate_path} holds no Recipe node")
    candidate = next(iter(scratch.recipes.values()))

    reference = _find(library, reference_id) if reference_id else None
    if reference is None:
        reference = library.recipes.get(candidate.id)
    if reference is None:
        raise SystemExit(
            "no reference to compare against; pass --against with a recipe id"
        )

    print(f"candidate  {candidate.name}  (level {candidate.enrichment_level})")
    print(f"reference  {reference.name}\n")
    print(compare(reference, candidate).report())
    return 0


def _report(findings) -> None:
    for finding in findings:
        print(finding)
    errors = sum(1 for f in findings if f.level == ERROR)
    warnings = sum(1 for f in findings if f.level == WARNING)
    print(f"\n{len(findings)} findings ({errors} errors, {warnings} warnings)")


if __name__ == "__main__":
    sys.exit(main())
