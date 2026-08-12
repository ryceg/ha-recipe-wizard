"""Asking the one question there is to ask: where are the recipes?

There is nothing to authenticate and nothing to discover, so the flow is a single
step over a single field -- and the whole of its substance is Bronze
``test-before-configure``: it **loads the library** before it writes an entry, in
the executor, and turns each distinct failure into its own message. A flow that
accepted any string and let ``async_setup_entry`` fail later would tell the user
"retrying setup" from a log they are not reading.

There is exactly one recipe library, so a second entry would be meaningless:
``single_config_entry: true`` in the manifest makes Home Assistant abort the
second flow itself, which is how ``unique-config-entry`` is satisfied here.

Module-scope ``homeassistant`` imports are correct in this file -- ADR 0002
confines the deferred-import pattern to ``__init__.py``, which is the module that
runs when the CLI imports the library.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import CONF_RECIPES_DIR, DOMAIN
from .loader import RecipeLibraryError, load_library

_LOGGER = logging.getLogger(__name__)

#: The entry title. Fixed, because there is only ever one entry.
TITLE = "Recipe Wizard"


class RecipeWizardConfigFlow(ConfigFlow, domain=DOMAIN):
    """Configure where the recipe documents live."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the directory, try to load it, and only then write the entry."""
        # ``<config>/recipes``, which is where ``core.library.DEFAULT_RECIPES``
        # resolves to once the integration is installed. Asked of Home Assistant
        # rather than computed from ``__file__`` so the suggestion is still right
        # when ``custom_components`` is a symlink, which is the usual dev setup.
        suggestion = self.hass.config.path("recipes")
        errors: dict[str, str] = {}
        # Always present, so a message using ``{detail}`` can never render the
        # placeholder literally.
        placeholders: dict[str, str] = {"detail": ""}

        if user_input is not None:
            suggestion = user_input[CONF_RECIPES_DIR]
            recipes_dir = self._resolve(suggestion)
            try:
                library = await self.hass.async_add_executor_job(
                    load_library, recipes_dir
                )
            except RecipeLibraryError as err:
                errors["base"] = err.error_key
                placeholders["detail"] = err.detail
            except Exception:  # noqa: BLE001 - the form must survive anything
                _LOGGER.exception(
                    "Unexpected error loading recipes from %s", recipes_dir
                )
                errors["base"] = "unknown"
            else:
                _LOGGER.debug(
                    "Recipe library at %s holds %d recipes", recipes_dir, len(library)
                )
                return self.async_create_entry(
                    title=TITLE, data={CONF_RECIPES_DIR: str(recipes_dir)}
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {vol.Required(CONF_RECIPES_DIR, default=suggestion): str}
            ),
            errors=errors,
            description_placeholders=placeholders,
        )

    def _resolve(self, raw: str) -> Path:
        """Absolute path for what the user typed.

        A relative path is read against the Home Assistant configuration
        directory, not the process's working directory. "recipes" is the obvious
        thing to type and the working directory of a supervised install is not
        somewhere a user has ever looked.
        """
        path = Path(raw.strip()).expanduser()
        return path if path.is_absolute() else Path(self.hass.config.path(str(path)))
