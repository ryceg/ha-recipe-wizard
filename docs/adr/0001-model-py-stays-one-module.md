# `model.py` stays one module

At ~800 lines `model.py` is the largest file in the library and it looks like it
wants splitting — the obvious cut being the JSON-LD reader out from the types it
produces. We are not doing it: every `parse` classmethod sits with the type it
builds, and all of them share one tolerance for the `rw:` prefix being present
or absent (`_get`). Splitting would put the knowledge of how a `Storage` is
spelled on disk in a different file from `Storage` itself, so adding a property
would mean editing two places that must agree — the knowledge spreads rather
than concentrates. Size is not the same thing as a module doing too much.

## Considered options

- **Split reader from model** (`model.py` + `read.py`). Rejected above.
- **Split by domain area** (ingredients / steps / recipe / storage). Rejected for
  the same reason plus a worse one: `Recipe.parse` reaches every other type, so
  the imports would be circular or the file would be a facade over four others.
- **Leave it.** Chosen. It is deep, not shallow: `Recipe.parse(node)` is a small
  interface over the whole on-disk format.

Recorded because a review that measures modules by line count will suggest the
split again. If you are here to reverse this, the question to answer first is
where the `rw:`-prefix rule lives afterwards.
