"""Known GitHub App/user token families never become AI input or output."""

import pytest

from app.core.ai_privacy import public_ai_question


@pytest.mark.parametrize(
    "prefix", ["ghp_", "gho_", "ghu_", "ghs_", "ghr_", "github_pat_", "sb_secret_"]
)
def test_modern_token_shapes_are_rejected_without_echoing_them(prefix):
    synthetic = prefix + "syntheticnotasecret" * 3
    with pytest.raises(ValueError) as error:
        public_ai_question("An untrusted repository excerpt contains " + synthetic)
    assert synthetic not in str(error.value)


def test_ordinary_github_discussion_is_not_a_credential():
    text = "A GitHub App can read selected repositories."
    assert public_ai_question(text) == text


@pytest.mark.parametrize(
    "text",
    [
        'AWS_ACCESS_KEY_ID = "AKIA' + "S" * 16 + '"',
        'AWS_ACCESS_KEY_ID = "ASIA' + "S" * 16 + '"',
        'AWS_SECRET_ACCESS_KEY = "synthetic-private-canary"',
        'AWS_SESSION_TOKEN = "synthetic-private-canary"',
        'GITHUB_TOKEN = "synthetic-private-canary"',
    ],
)
def test_repository_credentials_are_withheld_from_references_and_generated_prose(text):
    from app.schemas.conversation_tutor import explanatory_text
    from app.services.github_projects import reference

    assert reference("source", "config.json", text, "a" * 40) is None
    with pytest.raises(ValueError):
        explanatory_text(text)
