"""The vendored layout, and the two ways it can quietly break."""

import subprocess
import sys
from pathlib import Path

from custom_components.recipe_wizard.core.library import DEFAULT_FOODS, DEFAULT_RECIPES

ROOT = Path(__file__).resolve().parents[1]

# Import the library with ``homeassistant`` made unimportable, in a subprocess
# so the block cannot leak into the rest of the suite.
_IMPORT_WITHOUT_HA = """
import sys


class Blocker:
    def find_spec(self, name, path=None, target=None):
        if name == "homeassistant" or name.startswith("homeassistant."):
            raise ImportError(f"{name} was imported at module scope")
        return None


sys.meta_path.insert(0, Blocker())

from custom_components.recipe_wizard.core import Library, schedule  # noqa: F401
"""


def test_core_imports_without_home_assistant_installed():
    """The integration package's ``__init__`` runs first on every core import.

    A top-level ``from homeassistant... import`` there would drag Home Assistant
    into the CLI and into these tests, which is why the glue defers its imports.
    """
    result = subprocess.run(
        [sys.executable, "-c", _IMPORT_WITHOUT_HA],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr


def test_cli_trampoline_still_finds_the_library():
    """``python -m recipe_wizard`` is documented, and in the enrich-recipe skill."""
    result = subprocess.run(
        [sys.executable, "-m", "recipe_wizard", "--list"],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "urn:recipe:" in result.stdout


def test_default_paths_survive_the_move_under_custom_components():
    """Foods ship with the integration; recipes sit beside ``custom_components``."""
    assert DEFAULT_FOODS.is_file()
    assert DEFAULT_FOODS.parent.parent.name == "recipe_wizard"
    assert DEFAULT_RECIPES.is_dir()
    assert any(DEFAULT_RECIPES.glob("*.json"))
