"""Fixtures for the integration suite.

**Why this is a second suite.** ``pytest-homeassistant-custom-component``
installs autouse fixtures that attach to every test in the session, so with the
harness importable all 220 library tests error before they run. The two suites
therefore cannot share an interpreter, let alone a directory: ``tests/`` runs on
bare Python and proves the library needs nothing, ``tests_ha/`` runs under the
harness and is the only place Home Assistant exists. See
``docs/integration.md`` and ``.github/workflows/ci.yml`` for the two commands.

The harness also cannot run on Windows -- ``homeassistant.runner`` imports
``fcntl`` -- so this suite runs in Docker locally and on ``ubuntu-latest`` in CI.

Premises are built with ``tests/support.py`` rather than a second builder living
here. Its docstring is the argument: a test that names a real recipe to mean "a
recipe like this" stops being readable at two hundred recipes, and a duplicate
builder would drift from the on-disk format the reader actually parses.
"""

from __future__ import annotations

import shutil
from collections.abc import Generator
from pathlib import Path

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.recipe_wizard.const import CONF_RECIPES_DIR, DOMAIN

pytest_plugins = "pytest_homeassistant_custom_component"

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def custom_integration(enable_custom_integrations: None) -> None:
    """Let the loader find ``custom_components/recipe_wizard``.

    Not autouse: the loader and fingerprint tests are plain synchronous functions
    with no Home Assistant in them, and the harness fixture drags in a whole
    ``hass`` instance to clear one cache.
    """
    return


@pytest.fixture
def recipes_dir(tmp_path: Path) -> Path:
    """A writable copy of the real corpus.

    The real one, because "does the integration load the recipes this project
    actually ships" is a question worth asking of the shipped documents. Copied,
    because several tests need to break, add to or delete from it.
    """
    target = tmp_path / "recipes"
    shutil.copytree(REPO_ROOT / "recipes", target)
    return target


@pytest.fixture
def config_entry(recipes_dir: Path) -> MockConfigEntry:
    """An entry pointing at the copied corpus, not yet added to ``hass``."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Recipe Wizard",
        data={CONF_RECIPES_DIR: str(recipes_dir)},
    )


@pytest.fixture
async def loaded_entry(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    custom_integration: None,
) -> MockConfigEntry:
    """The entry, set up and loaded, with its runtime data in place."""
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    return config_entry


@pytest.fixture(autouse=True)
def _no_stray_files(tmp_path: Path) -> Generator[None]:
    """A guard rail, not a fixture with a purpose of its own.

    Every test in this suite works inside ``tmp_path``. If one ever writes into
    the real ``recipes/`` directory the corpus is ground truth for the library
    suite, so the failure would show up two directories away.
    """
    before = sorted(p.name for p in (REPO_ROOT / "recipes").iterdir())
    yield
    assert sorted(p.name for p in (REPO_ROOT / "recipes").iterdir()) == before
