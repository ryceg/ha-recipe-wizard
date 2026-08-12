"""ISO 8601 duration parsing, without pulling in a dependency.

Recipes use durations for two unrelated jobs: step timers (PT20M) and storage
life (P2M). Months and years have no fixed length, so they are expanded with a
nominal conversion and flagged. That is fine for "keeps 2 months frozen" and
would not be fine for anything doing date arithmetic against a calendar, so the
flag is carried rather than dropped.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_PATTERN = re.compile(
    r"^P(?!$)"
    r"(?:(?P<years>\d+(?:\.\d+)?)Y)?"
    r"(?:(?P<months>\d+(?:\.\d+)?)M)?"
    r"(?:(?P<weeks>\d+(?:\.\d+)?)W)?"
    r"(?:(?P<days>\d+(?:\.\d+)?)D)?"
    r"(?:T(?!$)"
    r"(?:(?P<hours>\d+(?:\.\d+)?)H)?"
    r"(?:(?P<minutes>\d+(?:\.\d+)?)M)?"
    r"(?:(?P<seconds>\d+(?:\.\d+)?)S)?"
    r")?$"
)

_NOMINAL_SECONDS = {
    "years": 365.2425 * 86400,
    "months": 30.436875 * 86400,
    "weeks": 7 * 86400,
    "days": 86400,
    "hours": 3600,
    "minutes": 60,
    "seconds": 1,
}


class DurationError(ValueError):
    """A duration string was not valid ISO 8601."""


@dataclass(frozen=True, slots=True)
class Duration:
    """A parsed duration, in seconds, remembering whether it is nominal."""

    seconds: float
    text: str
    nominal: bool = False
    """True when years or months were involved, so the length is approximate."""

    def __str__(self) -> str:
        return self.text

    def human(self) -> str:
        """A short human rendering, chosen by magnitude."""
        s = self.seconds
        if s == 0:
            return "immediately"
        if s < 60:
            return f"{s:g} sec"
        if s < 3600:
            return f"{s / 60:g} min"
        if s < 86400:
            hours, rem = divmod(s, 3600)
            mins = rem / 60
            return f"{hours:g} hr" + (f" {mins:g} min" if mins else "")
        # Nominal durations came from months or years, so rendering them as a
        # precise number of days ("91.3106 days") implies a precision the unit
        # never had.
        if self.nominal and s >= 27 * 86400:
            months = s / _NOMINAL_SECONDS["months"]
            if months >= 12:
                return f"{months / 12:.0f} years"
            return f"{months:.0f} months"
        return f"{s / 86400:.0f} days"


def parse_duration(text: str | None) -> Duration | None:
    """Parse an ISO 8601 duration such as ``PT20M``, ``P3D`` or ``PT0S``."""
    if text is None:
        return None
    if isinstance(text, Duration):
        return text
    raw = str(text).strip()
    if raw in ("P0D", "PT0S", "P0Y"):
        return Duration(0.0, raw)
    match = _PATTERN.match(raw)
    if not match:
        raise DurationError(f"not an ISO 8601 duration: {text!r}")
    total = 0.0
    nominal = False
    for key, value in match.groupdict().items():
        if value is None:
            continue
        if key in ("years", "months"):
            nominal = True
        total += float(value) * _NOMINAL_SECONDS[key]
    return Duration(total, raw, nominal)
