# The integration package imports Home Assistant lazily

`custom_components/recipe_wizard/__init__.py` must not import `homeassistant` at
module scope, which is a deliberate deviation from every Home Assistant example
you will find. The reason is the vendored layout: the library is a subpackage at
`custom_components/recipe_wizard/core/`, so importing anything from it executes
the integration package's `__init__.py` first. A top-level
`from homeassistant.core import HomeAssistant` there would make the CLI, the
enrichment workflow and all ~190 library tests require Home Assistant to be
installed — a 300 MB dependency to run `--validate` on a recipe. So the glue uses
`if TYPE_CHECKING:` for annotations (with `from __future__ import annotations`)
and imports inside the function bodies that need them.

`tests/test_packaging.py::test_core_imports_without_home_assistant_installed`
enforces this by importing the core in a subprocess with `homeassistant` blocked,
so it fails whether or not Home Assistant is installed locally. If that test goes
red after someone tidies the imports into idiomatic HA style, the test is right
and the tidying is wrong.

## Consequences

**hassfest warns about `CONFIG_SCHEMA`, and we accept the warning.** Any
integration implementing `async_setup` is expected to declare `CONFIG_SCHEMA`
(here it would be `cv.config_entry_only_config_schema(DOMAIN)`), and every way of
declaring it needs `homeassistant.helpers.config_validation` imported at module
scope in this file. We implement `async_setup` because Bronze's `action-setup`
requires actions to be registered there, so the two rules genuinely conflict.

It stays a warning and CI stays green. At runtime the only thing a missing
`CONFIG_SCHEMA` costs is YAML validation of a domain that accepts no YAML
configuration. A guarded `try: import ... except ImportError:` would silence it
while turning a clean invariant into a subtle one — and would swallow a real
import failure — so we do not. Reproduce it with:

```
docker run --rm -v "$(pwd -W)://github/workspace" ghcr.io/home-assistant/hassfest
```


Deferred imports cost nothing at runtime (Home Assistant imports the module once)
but they do mean this one file reads oddly. Confine the pattern to
`__init__.py` — every other module in the integration (`config_flow.py`,
`sensor.py`, `todo.py`) is only ever imported *by* Home Assistant and should
import normally at module scope.
