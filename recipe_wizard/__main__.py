"""Command line entry point: ``python -m recipe_wizard``."""

from __future__ import annotations

import argparse
import json
import sys

from .library import Library
from .render import render_table
from .resolve import UnresolvableComponent, resolve, resolve_component
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
    parser.add_argument("--components", action="store_true",
                        help="resolve sub-recipes and show their numbers")
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
    resolution = resolve(library, recipe.id, strict=False)

    print(f"\n{recipe.name.upper()}")
    if recipe.url:
        print(recipe.url)
    if resolution.batch_yield_g:
        print(f"Yield: {resolution.batch_yield_g:.0f} g "
              f"({recipe.yield_basis})")
    for entry in recipe.storage:
        keeps = entry.keeps.human() if entry.keeps else "unspecified"
        line = f"Storage: {entry.method}, keeps {keeps}"
        if entry.quality_window:
            line += f" (at its best for {entry.quality_window.human()})"
        if entry.condition:
            line += f" - {entry.condition}"
        print(line)
    for method in recipe.unsuitable_for:
        print(f"Storage: not suitable for {method}")
    print()
    print(render_table(recipe, resolution))

    if args.components:
        for use in recipe.components:
            print()
            try:
                sub = resolve_component(library, use, strict=False)
            except UnresolvableComponent as exc:
                print(f"  {use.label}: {exc}")
                continue
            print(f"  {sub.summary()}")
            for ingredient in sub.ingredients:
                print(f"    {ingredient}")
            for entry in sub.change_log:
                print(f"    . {entry}")
            for warning in sub.warnings:
                print(f"    ! {warning}")

    if args.plan:
        plan = schedule(recipe)
        print(f"\nPLAN  total {plan.total_s / 60:.0f} min | "
              f"hands-on {plan.active_s / 60:.0f} min | "
              f"hands-off {plan.unattended_s / 60:.0f} min")
        for step in plan.steps:
            print(f"  {step.start_s / 60:6.1f} -> {step.end_s / 60:6.1f}  "
                  f"{step.step_id:22} [{step.attention}]")
        for chain in plan.rigid_chains:
            print("  no pause allowed: " + " -> ".join(chain))
        for warning in plan.warnings:
            print(f"  ! {warning}")

    if args.validate:
        print()
        _report(validate_recipe(recipe, library))

    return 0


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
