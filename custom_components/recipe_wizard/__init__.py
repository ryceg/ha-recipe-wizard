"""The Recipe Wizard Home Assistant integration.

The Home Assistant glue lands here -- ``async_setup``, ``async_setup_entry``,
``async_unload_entry``. The library it wraps is the ``core`` subpackage.

Keep ``homeassistant`` imports out of module scope in this file. Importing
``custom_components.recipe_wizard.core`` runs this module first, so a top-level
``from homeassistant... import`` here would make the CLI and the library tests
require Home Assistant to be installed. Use ``TYPE_CHECKING`` for annotations
and import inside the function bodies; ``tests/test_packaging.py`` enforces it.
"""
