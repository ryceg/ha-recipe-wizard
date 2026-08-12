# Recipe Wizard in Home Assistant

Recipe Wizard turns a folder of recipe files into something you can cook from on
a screen in your kitchen.

It is built around two things:

* **A cook-along.** One step at a time, in the order you should do it, with the
  amounts already worked out for the batch size you are making and a timer that
  says what it is waiting for. A screen you do not have to touch with dough on
  your hands.
* **A shopping list.** One line per food, added up across the whole dish
  including any sub-recipes. Butter that gets melted in one part of the recipe
  and softened in another is *one thing to buy* and *two things to have ready*,
  and the list says both.

Everything happens on your own machine. Recipe Wizard does not talk to the
internet and does not send your recipes anywhere.

> **A note on this version.** This release is the plumbing only: it finds your
> recipes, checks it can read them, and keeps watching the folder. The cook-along
> and shopping-list screens come next. If you install it now, you will see the
> integration listed and no entities yet.

## What it needs from you

A folder of recipe files. Each recipe is one file ending in `.json`, in the
structured format this project defines. Folders inside your recipe folder are
searched too, so you can organise however you like.

You create and edit those files outside Home Assistant, using the command-line
tool that comes with this project — see the main [README](../README.md). Recipe
Wizard reads them; it never writes to them.

## Installing it

### With HACS (recommended)

1. In Home Assistant, open **HACS**.
2. Open the three-dot menu in the top right and choose **Custom repositories**.
3. Paste in `https://github.com/ryceg/ha-recipe-wizard`, choose the category
   **Integration**, and select **Add**.
4. Find **Recipe Wizard** in the list and select **Download**.
5. Restart Home Assistant.

### By hand

1. Download or clone this project.
2. Copy the whole folder `custom_components/recipe_wizard` into the
   `custom_components` folder next to your `configuration.yaml`. If there is no
   `custom_components` folder, create one. You should end up with
   `custom_components/recipe_wizard/manifest.json`.
3. Restart Home Assistant.

Either way, put your recipe files in a folder called `recipes` next to your
`configuration.yaml`. That is the folder Recipe Wizard will offer you by default.

## Setting it up

1. Go to **Settings → Devices & services → Add integration**.
2. Search for **Recipe Wizard** and select it.
3. You are asked for one thing: the **recipe folder**. The box is pre-filled with
   `recipes` next to your `configuration.yaml`, which is the usual place. If you
   keep your recipes somewhere else, type the full path instead. A plain name
   with no path is understood as a folder next to your `configuration.yaml`.
4. Select **Submit**.

Recipe Wizard reads every recipe before it saves anything. If something is wrong
it tells you what, and you can correct the folder and try again without starting
over. There is nothing else to configure, and no username, password or key of any
kind.

You can only add Recipe Wizard once. There is one recipe collection, so a second
copy would have nothing different to show.

## If setup will not go through

| What it says | What to do |
| --- | --- |
| There is no folder at… | Check the spelling. If you have not made the folder yet, create it and put at least one recipe in it. |
| No recipes were found in… | The folder exists but has no recipe files in it. Recipe Wizard looks for files ending in `.json`. |
| One of the recipe files could not be read… | The message names the file. It is either not valid JSON, or it has no `@id` line giving the recipe its identity. Fix or move that file and try again. |
| Recipe Wizard could not read its own list of foods… | This one is not your fault: a file that ships inside the integration is missing or damaged. Re-download the integration and restart Home Assistant. |
| Something unexpected went wrong | Look in **Settings → System → Logs** for the details, and please open an issue with what you find. |

If setup succeeded before and the integration later shows as *retrying*, the
usual cause is the same list above — most often a recipe file that has been
edited and is no longer valid. The log names the file.

## Keeping up with changes

Recipe Wizard checks the recipe folder **every 15 minutes**, so a recipe you add
or edit turns up on its own and you do not have to restart Home Assistant.

The check itself is deliberately cheap: it looks at *when* each file was last
changed and only re-reads the recipes when something has actually moved. Adding
a recipe is a thing you do a few times a week, not a few times a second, so 15
minutes is generous on purpose.

## Removing it

1. Go to **Settings → Devices & services**.
2. Find **Recipe Wizard**, open its three-dot menu and choose **Delete**.

That removes the integration's own settings and any entities it created. **Your
recipe files are not touched.** They are your own documents, they live outside
the integration folder, and nothing in Recipe Wizard ever deletes or edits them —
so you can delete the integration and add it back later against the same folder.

To remove the software as well, delete it in HACS, or delete the
`custom_components/recipe_wizard` folder if you installed it by hand, and then
restart Home Assistant.

## Things it does not do

Worth knowing before you rely on it:

* **You edit recipes outside Home Assistant.** There is no screen for writing or
  changing a recipe. That is done with the command-line tool.
* **Nutrition is not calculated.** Recipe Wizard works in grams and millilitres,
  not calories or carbohydrates. If you are counting carbohydrates — for diabetes
  or any other reason — do not treat anything here as a nutrition figure, and talk
  to your care team about how you count. This is general information, not medical
  advice.
* **Some weights are honestly unknown.** Where a recipe gives a measure that
  cannot be turned into a weight — "a splash of milk", or a cup of something
  whose density is not known — the list says so rather than guessing. A shopping
  line can read *"at least 500 g, plus 1 line with no weight"*, and that is the
  truth rather than a gap.
* **Steps from different recipes are not woven together.** A cake and its
  frosting each get their own running order. Recipe Wizard will not decide to slot
  the frosting into the gap while the cake cools, because no recipe says it is
  safe to.
* **Recipes that point at a cookbook stay pointing at a cookbook.** If a recipe
  says "use the sauce on page 308", Recipe Wizard tells you to go and get the
  book. It leaves that off the shopping list on purpose rather than pretending it
  needs nothing.

## For contributors

The integration is a thin layer over `custom_components/recipe_wizard/core/`, a
stdlib-only library with no Home Assistant dependency. Two things follow from
that and are worth knowing before changing anything:

* `custom_components/recipe_wizard/__init__.py` must not import `homeassistant`
  at module scope. See
  [`adr/0002`](adr/0002-no-home-assistant-imports-at-module-scope.md);
  `tests/test_packaging.py` enforces it.
* Every call into the library goes through `hass.async_add_executor_job`. It does
  synchronous file I/O, and the event loop must not wait on a disk.

There are two test suites, and they cannot share an interpreter — the Home
Assistant test harness installs autouse fixtures that attach to every test in the
session, which breaks all 220 library tests:

```bash
python -m pytest -q                 # the library, on bare Python, no Home Assistant
```

The integration suite needs Home Assistant and cannot run on Windows
(`homeassistant.runner` imports `fcntl`), so run it in a container:

```bash
docker run --rm -v "$(pwd):/app" -w /app rw-hass-test \
    python -m pytest -q -o asyncio_mode=auto tests_ha
```

`-o asyncio_mode=auto` is required; without it every test errors on the harness's
autouse async fixtures. Both suites also run in CI on `ubuntu-latest`, along with
`hassfest` and HACS validation — see `.github/workflows/ci.yml`.

`custom_components/recipe_wizard/quality_scale.yaml` records where the integration
stands against the Home Assistant quality scale, with a reason against every
exemption.
