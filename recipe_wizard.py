"""``python -m recipe_wizard`` from the repo root.

The library lives at ``custom_components/recipe_wizard/core/`` so that HACS can
ship it, which makes its real dotted path a mouthful. This trampoline keeps the
documented command working; it is not part of the installed integration.
"""

import sys

from custom_components.recipe_wizard.core.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
