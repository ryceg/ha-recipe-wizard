"""Loading recipes and foods off disk, and resolving ``@id`` references.

Identity lives in the ``@id``, never the filename, so a recipe can be renamed
without breaking every parent that references it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

from .model import Recipe, RecipeFamily

# The food bank ships with the integration, so it is always package-relative.
DEFAULT_FOODS = Path(__file__).resolve().parent.parent / "data" / "foods.json"

# Recipes are the user's, not ours, so they sit beside ``custom_components``
# rather than inside it: the repo root when developing, and the Home Assistant
# config directory once installed. The config flow passes an explicit path, so
# this is only the default for the CLI and the tests.
DEFAULT_RECIPES = Path(__file__).resolve().parents[3] / "recipes"


class LibraryProblem(Exception):
    """Anything that stops a library being read. The base worth catching.

    Every subclass carries ``source``: the file the problem is in, where there is
    one. Without it a caller has to re-walk the directory to find out which of
    two hundred documents it was — and that is exactly what the Home Assistant
    integration was doing before this existed.
    """

    def __init__(self, message: str, source: Path | None = None) -> None:
        super().__init__(message)
        self.source = source


class LibraryError(LibraryProblem, LookupError):
    """A referenced ``@id`` could not be resolved.

    Still a ``LookupError``, because that is what a failed lookup is and callers
    catch it as one.
    """


class DocumentError(LibraryProblem):
    """One document could not be read or parsed.

    The message names the file, because the enrichment loop runs against ~200 of
    them and ``Expecting ',' delimiter: line 1 column 37`` on its own does not
    say which one to open.
    """


class FoodBankError(DocumentError):
    """The food bank could not be read.

    A subclass because the bank *is* a document, and a distinct type because the
    instruction to the user is different: the bank ships with the library, so a
    broken one means a broken install rather than a recipe they mistyped.
    """


@dataclass(slots=True)
class Food:
    """A food concept: the thing that makes shopping lists merge."""

    id: str
    name: str
    density_g_per_ml: float | None = None
    density_confidence: str = "medium"
    unit_mass_g: float | None = None
    discrete: bool = False
    form_sensitive: bool = False
    """Density depends on the cut or pack as much as on the food. "The 3 cup
    measure for 350 g is for elbow macaroni only" -- so a volume measure of one
    of these is not usable without knowing the form."""
    note: str | None = None
    aliases: list[str] = field(default_factory=list)


class FoodBank:
    """The food concept bank, indexed by id and by alias."""

    def __init__(self, foods: dict[str, Food]) -> None:
        self._by_id = foods
        self._by_alias: dict[str, Food] = {}
        for food in foods.values():
            for alias in [food.name, *food.aliases]:
                self._by_alias.setdefault(alias.strip().lower(), food)

    @classmethod
    def load(cls, path: Path | str = DEFAULT_FOODS) -> "FoodBank":
        source = Path(path)
        try:
            data = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, ValueError) as err:
            raise FoodBankError(f"{source.name}: {err}", source) from err
        foods = {}
        for food_id, node in data.get("foods", {}).items():
            foods[food_id] = Food(
                id=food_id,
                name=node.get("name", food_id),
                density_g_per_ml=node.get("density_g_per_ml"),
                density_confidence=node.get("density_confidence", "medium"),
                unit_mass_g=node.get("unit_mass_g"),
                discrete=bool(node.get("discrete", False)),
                form_sensitive=bool(node.get("form_sensitive", False)),
                note=node.get("note"),
                aliases=node.get("aliases", []),
            )
        return cls(foods)

    def get(self, food_id: str | None) -> Food | None:
        if not food_id:
            return None
        return self._by_id.get(food_id)

    def match(self, text: str | None) -> Food | None:
        """Best-effort lookup by name, for lifting scraped ingredient strings."""
        if not text:
            return None
        return self._by_alias.get(text.strip().lower())

    def __len__(self) -> int:
        return len(self._by_id)


class Library:
    """An indexed collection of recipe and family documents."""

    def __init__(self) -> None:
        self.recipes: dict[str, Recipe] = {}
        self.families: dict[str, RecipeFamily] = {}
        self.foods = FoodBank({})

    @classmethod
    def load(
        cls,
        recipes_dir: Path | str = DEFAULT_RECIPES,
        foods_path: Path | str = DEFAULT_FOODS,
    ) -> "Library":
        library = cls()
        library.foods = FoodBank.load(foods_path)
        for path in sorted(Path(recipes_dir).rglob("*.json")):
            library.add_document(cls._read(path), path)
        return library

    @staticmethod
    def _read(path: Path) -> dict:
        """One document, with the failure naming the file it is in.

        ``json`` reports a line and a column and not a filename, which is fine
        when you are looking at the file you just edited and useless when a
        directory of two hundred is being loaded by something else -- the
        enrichment loop, or a Home Assistant config flow that has to put the
        answer in a form.
        """
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as err:
            raise DocumentError(f"{path.name}: {err}", path) from err

    def add_document(self, doc: dict, source: Path | None = None) -> None:
        """Index one JSON-LD document, which may hold a ``@graph`` of nodes."""
        nodes = doc.get("@graph") if isinstance(doc.get("@graph"), list) else [doc]
        for node in nodes:
            if not isinstance(node, dict):
                continue
            types = node.get("@type")
            types = types if isinstance(types, list) else [types]
            types = {str(t).removeprefix("rw:") for t in types if t}
            try:
                if "Recipe" in types:
                    recipe = Recipe.parse(node)
                    if not recipe.id:
                        raise LibraryError(f"recipe without @id in {source}", source)
                    self.recipes[recipe.id] = recipe
                elif "RecipeFamily" in types:
                    family = RecipeFamily.parse(node)
                    self.families[family.id] = family
            except LibraryProblem:
                raise
            except (ValueError, TypeError, KeyError) as err:
                # The model refused the node -- a duration that is not ISO 8601,
                # a quantity with no value. Same reasoning as ``_read``: the
                # caller needs the filename, and the model has never seen one.
                where = source.name if source else "document"
                raise DocumentError(f"{where}: {err}", source) from err

    def recipe(self, recipe_id: str) -> Recipe:
        try:
            return self.recipes[recipe_id]
        except KeyError:
            raise LibraryError(f"no recipe with @id {recipe_id!r}") from None

    def family(self, family_id: str) -> RecipeFamily:
        try:
            return self.families[family_id]
        except KeyError:
            raise LibraryError(f"no family with @id {family_id!r}") from None

    def variant_chain(self, recipe_id: str) -> list[Recipe]:
        """Walk ``isVariantOf`` to the base, returned base-first.

        Cycles raise rather than hang; a recipe that is its own ancestor is a
        data error worth surfacing loudly.
        """
        chain: list[Recipe] = []
        seen: set[str] = set()
        current: str | None = recipe_id
        while current:
            if current in seen:
                raise LibraryError(
                    f"variant cycle through {current!r}: "
                    + " -> ".join(r.id for r in reversed(chain))
                )
            seen.add(current)
            recipe = self.recipe(current)
            chain.append(recipe)
            current = recipe.is_variant_of
        chain.reverse()
        return chain

    def members_of(self, family_id: str) -> list[Recipe]:
        return [self.recipe(m) for m in self.family(family_id).members
                if m in self.recipes]

    def __iter__(self) -> Iterator[Recipe]:
        return iter(self.recipes.values())

    def __len__(self) -> int:
        return len(self.recipes)
