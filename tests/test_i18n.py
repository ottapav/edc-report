import re

import pandas as pd
import pytest

import i18n


def _placeholders(text: str) -> list[str]:
    return sorted(re.findall(r"\{\w+\}", text))


@pytest.mark.parametrize("lang", [lg for lg in i18n.LANGS if lg != "en"])
def test_every_language_has_the_keys_and_placeholders_of_english(lang):
    en, other = i18n.STRINGS["en"], i18n.STRINGS[lang]
    assert set(other) == set(en)
    for key, text in en.items():
        assert _placeholders(other[key]) == _placeholders(text), (lang, key)
        assert other[key].strip(), (lang, key)


def test_every_language_has_a_label_in_the_switch():
    assert set(i18n.LANG_LABELS) == set(i18n.LANGS) == set(i18n.STRINGS)


def test_german_number_and_date_formats():
    assert i18n.fmt_num(1234567.891, "de", 1) == "1.234.567,9"
    assert i18n.fmt_num(12.5, "de", 2) == "12,50"
    assert i18n.fmt_num(1234.5, "en", 1) == "1,234.5"           # the others are unchanged
    assert i18n.fmt_num(1234.5, "cs", 1) == "1\u202f234,5"
    assert i18n.fmt_pct(52.34, "de") == "52,3\u00a0%"
    ts = pd.Timestamp("2026-03-07")
    assert i18n.fmt_date(ts, "de") == "07.03.2026" == i18n.fmt_date(ts, "cs")
    assert i18n.fmt_date(ts, "en") == "2026-03-07"
    assert i18n.month_label(ts, "de") == "Mär 2026"
    assert i18n.plotly_separators("de") == ",."
    assert i18n.decimal_char("de") == "," and i18n.decimal_char("en") == "."
    assert i18n.date_picker_format("de") == "DD.MM.YYYY"
