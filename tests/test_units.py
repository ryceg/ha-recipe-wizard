"""Unit handling, and the divergences that motivated it."""

import pytest

from custom_components.recipe_wizard.core.duration import format_duration, parse_duration
from custom_components.recipe_wizard.core.units import Quantity, UnitError, to_grams, to_millilitres


def test_tablespoon_differs_by_system():
    """An Australian tablespoon is 35% larger than a US one.

    RecipeTin Eats is Australian, so "2-4 tbsp milk" there is 40-80 mL. A
    resolver that assumes US units understates it by a third.
    """
    tbsp = Quantity(1, "tbsp")
    assert to_millilitres(tbsp, "AU") == 20.0
    assert to_millilitres(tbsp, "US") == pytest.approx(14.7868, rel=1e-4)
    assert to_millilitres(tbsp, "metric") == 15.0


def test_cup_differs_by_system():
    cup = Quantity(1, "cup")
    assert to_millilitres(cup, "AU") == 250.0
    assert to_millilitres(cup, "US") == pytest.approx(236.588, rel=1e-4)


def test_teaspoon_is_the_same_everywhere():
    tsp = Quantity(1, "tsp")
    assert to_millilitres(tsp, "AU") == 5.0
    assert to_millilitres(tsp, "metric") == 5.0


def test_stick_is_a_mass_not_a_volume():
    """Both sources call the same thing "2 sticks" and disagree on the grams."""
    assert to_grams(Quantity(2, "stick")) == pytest.approx(226.8, abs=0.1)


def test_volume_without_density_refuses_rather_than_guesses():
    with pytest.raises(UnitError, match="without a density"):
        to_grams(Quantity(1, "cup"), system="AU")


def test_count_without_unit_mass_refuses():
    with pytest.raises(UnitError, match="without a per-unit mass"):
        to_grams(Quantity(4, "large"))


def test_case_sensitive_tablespoon_alias():
    assert Quantity(1, "T").unit == "tbsp"
    assert Quantity(1, "t").unit == "tsp"


def test_display_text_survives_normalisation():
    q = Quantity(2.5, "cup", "2 1/2 cups")
    assert str(q) == "2 1/2 cups"
    assert q.scaled(2).display is None, "a scaled quantity's display no longer holds"


def test_unitcode_and_unittext_both_parse():
    assert Quantity.from_jsonld({"value": 500, "unitCode": "GRM"}).unit == "g"
    assert Quantity.from_jsonld({"value": 3, "unitText": "tsp"}).unit == "tsp"


def test_storage_durations_are_flagged_nominal():
    """Months have no fixed length; "keeps 2 months frozen" is approximate."""
    assert parse_duration("P3D").nominal is False
    assert parse_duration("P3M").nominal is True
    assert parse_duration("PT20M").seconds == 1200
    assert parse_duration("PT0S").seconds == 0


def test_a_written_duration_reads_back_the_same():
    """Anything that writes a document has to round-trip through the parser.

    The two halves drifting apart is silent: a formatter that emits "PT90M"
    where the parser wants "PT1H30M" produces a document that loads with the
    wrong time, or does not load at all.
    """
    for seconds in (0, 30, 1200, 3600, 5430, 86400, 90061):
        written = format_duration(seconds)
        assert parse_duration(written).seconds == seconds, written
    assert format_duration(0) == "PT0S"
    assert format_duration(-5) == "PT0S", "a negative duration is not a duration"
