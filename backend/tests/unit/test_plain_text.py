"""Long source identifiers stay plain text; URL forms still fail closed."""

import pytest

from app.domain.lesson_spec.fields import plain_text


def test_long_hyphenated_source_is_preserved():
    value = "a-" * 8000
    assert plain_text(value) == value


@pytest.mark.parametrize(
    "value",
    [
        "custom+scheme://host",
        "HTTPS://host",
        "mailto:a",
        "javascript:x",
        "data:x",
        "www.x",
        "//host",
    ],
)
def test_url_forms_are_still_rejected(value):
    with pytest.raises(ValueError, match="URLs"):
        plain_text(value)
