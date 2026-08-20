"""Asking the one question there is to ask: where are the recipes?

There is nothing to authenticate and nothing to discover, so the flow is a single
field asked twice -- once when the integration is added, once when the folder
moves -- and the whole of its substance is Bronze ``test-before-configure``: it
**loads the library** before it writes an entry, in the executor, and turns each
distinct failure into its own message. A flow that accepted any string and let
``async_setup_entry`` fail later would tell the user "retrying setup" from a log
they are not reading.

**Reconfiguration is a real gap rather than a formality here** (Gold
``reconfiguration-flow``). The single thing this integration knows is a path, and
a path is the single thing about a Home Assistant install that a user moves --
onto a bigger disk, out of ``/config``, into a share. Without this step the only
way to follow the folder was to delete the entry and add it back, which throws
away the entity registry entries every dashboard card points at, the cook-along
position in the entry's options, and the shopping list's ticks. So the reconfigure
step exists to keep ``entry_id`` -- which ``entity.py`` builds every ``unique_id``
from -- while the path underneath it changes.

The two steps share ``_async_checked_directory``, not by accident: a second copy
of the load-and-classify block would be a second set of error keys to keep in step
with ``strings.json``, and the failure a user hits while *moving* their recipes is
exactly the failure they hit while first finding them. What is deliberately *not*
shared is the suggestion each form opens on -- the user step offers
``<config>/recipes`` because a new user has nowhere else to have put them, and the
reconfigure step offers what is configured now, because that is the string being
edited.

There is exactly one recipe library, so a second *entry* would be meaningless:
``single_config_entry: true`` in the manifest makes Home Assistant abort a second
user flow itself, which is how ``unique-config-entry`` is satisfied here. Home
Assistant exempts ``SOURCE_RECONFIGURE`` from that abort, which is what makes
reconfiguring a single-entry integration possible at all.

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
        placeholders = self._placeholders()

        if user_input is not None:
            suggestion = user_input[CONF_RECIPES_DIR]
            recipes_dir, errors, placeholders = await self._async_checked_directory(
                suggestion
            )
            if recipes_dir is not None:
                return self.async_create_entry(
                    title=TITLE, data={CONF_RECIPES_DIR: str(recipes_dir)}
                )

        return self._form("user", suggestion, errors, placeholders)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Point the existing entry at another folder, keeping everything else.

        ``async_update_reload_and_abort`` with ``data_updates`` rather than
        ``data``: it rewrites the one key and reloads the entry, so the
        coordinator picks the new directory up immediately instead of at the next
        restart -- and it leaves ``entry.options`` alone, which is where
        ``cursor.py`` keeps the cook-along. A cook who moves their recipe folder
        mid-bake comes back to the same step.

        Nothing here migrates or copies files. The user moved the recipes; this
        step's only job is to check the new folder reads and then believe them.
        """
        entry = self._get_reconfigure_entry()
        suggestion = entry.data[CONF_RECIPES_DIR]
        errors: dict[str, str] = {}
        placeholders = self._placeholders()

        if user_input is not None:
            suggestion = user_input[CONF_RECIPES_DIR]
            recipes_dir, errors, placeholders = await self._async_checked_directory(
                suggestion
            )
            if recipes_dir is not None:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_RECIPES_DIR: str(recipes_dir)}
                )

        return self._form("reconfigure", suggestion, errors, placeholders)

    async def _async_checked_directory(
        self, raw: str
    ) -> tuple[Path | None, dict[str, str], dict[str, str]]:
        """Load the library at ``raw``; the path if it read, or why it did not.

        The one place this integration decides whether a directory is usable, and
        the reason both steps above are as short as they are. It returns the
        error mapping rather than raising because both callers want the same
        thing from a failure: the form back, with the message under it, and the
        text the user typed still in the box.
        """
        recipes_dir = self._resolve(raw)
        try:
            library = await self.hass.async_add_executor_job(load_library, recipes_dir)
        except RecipeLibraryError as err:
            return None, {"base": err.error_key}, self._placeholders(err.detail)
        except Exception:  # noqa: BLE001 - the form must survive anything
            _LOGGER.exception("Unexpected error loading recipes from %s", recipes_dir)
            return None, {"base": "unknown"}, self._placeholders()
        _LOGGER.debug(
            "Recipe library at %s holds %d recipes", recipes_dir, len(library)
        )
        return recipes_dir, {}, self._placeholders()

    def _form(
        self,
        step_id: str,
        suggestion: str,
        errors: dict[str, str],
        placeholders: dict[str, str],
    ) -> ConfigFlowResult:
        """The one field, defaulted to whatever the caller wants offered."""
        return self.async_show_form(
            step_id=step_id,
            data_schema=vol.Schema(
                {vol.Required(CONF_RECIPES_DIR, default=suggestion): str}
            ),
            errors=errors,
            description_placeholders=placeholders,
        )

    @staticmethod
    def _placeholders(detail: str = "") -> dict[str, str]:
        """Always present, so a message using ``{detail}`` can never render the
        placeholder literally."""
        return {"detail": detail}

    def _resolve(self, raw: str) -> Path:
        """Absolute path for what the user typed.

        A relative path is read against the Home Assistant configuration
        directory, not the process's working directory. "recipes" is the obvious
        thing to type and the working directory of a supervised install is not
        somewhere a user has ever looked.
        """
        path = Path(raw.strip()).expanduser()
        return path if path.is_absolute() else Path(self.hass.config.path(str(path)))
