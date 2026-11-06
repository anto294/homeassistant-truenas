"""Tests that every language has every text, and can show it."""

from __future__ import annotations

import json
from pathlib import Path
import re

import pytest

COMPONENT = Path(__file__).parent.parent / "custom_components" / "truenas_link"
LANGUAGES = sorted(path.name for path in (COMPONENT / "translations").glob("*.json"))


def _flat(data, prefix=""):
    """Return a translation file as {dotted key: text}."""
    result = {}
    for key, value in data.items():
        if isinstance(value, dict):
            result.update(_flat(value, f"{prefix}{key}."))
        else:
            result[f"{prefix}{key}"] = value

    return result


def _load(path):
    """Return a translation file, flattened."""
    return _flat(json.loads(path.read_text(encoding="utf-8")))


SOURCE = _load(COMPONENT / "strings.json")


def test_all_languages_are_checked():
    """A language that goes missing would pass the other tests."""
    assert LANGUAGES == [
        "en.json",
        "es.json",
        "it.json",
        "pt_BR.json",
        "ru.json",
        "sk.json",
    ]


@pytest.mark.parametrize("language", LANGUAGES)
def test_language_has_the_same_keys_as_strings_json(language):
    """A missing key shows English or nothing, and an extra one is a leftover."""
    keys = set(_load(COMPONENT / "translations" / language))

    assert keys == set(SOURCE)


@pytest.mark.parametrize("language", LANGUAGES)
def test_placeholders_are_the_same_in_each_text(language):
    """A wrong placeholder breaks the text at runtime."""
    texts = _load(COMPONENT / "translations" / language)

    for key, text in SOURCE.items():
        assert set(re.findall(r"{(\w+)}", texts[key])) == set(
            re.findall(r"{(\w+)}", text)
        ), key


def test_english_file_is_the_same_as_strings_json():
    """They are two copies of one text."""
    assert _load(COMPONENT / "translations" / "en.json") == SOURCE


@pytest.mark.parametrize(
    "path",
    [COMPONENT / "strings.json", *sorted((COMPONENT / "translations").glob("*.json"))],
    ids=lambda path: path.name,
)
def test_flow_title_only_asks_for_the_name(path):
    """A reauthentication flow only has the name, and a title can't go without one."""
    title = _load(path).get("config.flow_title", "")

    assert set(re.findall(r"{(\w+)}", title)) <= {"name"}


@pytest.mark.parametrize(
    "path",
    [COMPONENT / "strings.json", *sorted((COMPONENT / "translations").glob("*.json"))],
    ids=lambda path: path.name,
)
def test_access_level_options_are_short_and_explained(path):
    """The options only name the level, and each form says what the levels do."""
    texts = _load(path)

    assert "(" not in texts["selector.access_level.options.admin"]
    assert "(" not in texts["selector.access_level.options.read_only"]
    assert texts["config.step.user.data_description.access_level"]
    assert texts["options.step.init.data_description.access_level"]


@pytest.mark.parametrize(
    "path",
    [COMPONENT / "strings.json", *sorted((COMPONENT / "translations").glob("*.json"))],
    ids=lambda path: path.name,
)
def test_reauthentication_title_names_the_entry(path):
    """With several systems, the dialog has to say which one lost its key."""
    assert "{name}" in _load(path)["config.step.reauth_confirm.title"]
