"""Public support inputs and authored-copy privacy retain their exact boundaries."""

import pytest
from pydantic import ValidationError

from app.core.ai_privacy import credential_free_text, public_ai_question
from app.schemas.support import SupportDocument, SupportPassage, SupportQuestion
from app.schemas.support_http import SupportAskCreate, contextual_support_question
from app.services.support_readiness import support_document_digest
from app.support.knowledge import load_corpus_package, support_corpus_digest


@pytest.mark.parametrize(
    "body",
    [
        {"question": "Why is token: none displayed?"},
        {
            "question": "What about that warning?",
            "history": [{"role": "user", "text": "Why is token: none displayed?"}],
        },
        {
            "question": "What about that warning?",
            "history": [
                {"role": "user", "text": "token:"},
                {"role": "assistant", "text": "A placeholder is displayed."},
            ],
        },
    ],
)
def test_public_schema_rejects_the_exact_invalid_internal_question(body):
    with pytest.raises(ValidationError):
        SupportAskCreate.model_validate(body)


@pytest.mark.parametrize(
    "body",
    [
        {"question": "How do Trace hints work?"},
        {
            "question": "How do Trace hints work?",
            "history": [{"role": "assistant", "text": "token:"}],
        },
        {
            "question": "When are those reviews due?",
            "history": [
                {"role": "user", "text": "Why is token: none displayed?"},
                {"role": "assistant", "text": "token:"},
                {"role": "user", "text": "Explain Tasks review checkpoints."},
                {"role": "assistant", "text": "There are two scheduled reviews."},
            ],
        },
    ],
)
def test_valid_question_and_unused_history_keep_existing_semantics(body):
    checked = SupportAskCreate.model_validate(body)
    question = contextual_support_question(checked)
    assert SupportQuestion(question=question).question == question
    assert checked.model_dump(mode="json") == {"history": [], **body}


@pytest.mark.parametrize(
    "synthetic",
    [
        "AIza" + "A" * 35,
        "sk-" + "A" * 30,
        *(
            prefix + "syntheticnotasecret" * 3
            for prefix in ("ghp_", "gho_", "ghu_", "ghs_", "ghr_", "github_pat_", "sb_secret_")
        ),
        "AKIA" + "A" * 16,
        "ASIA" + "A" * 16,
        "eyJ" + "a" * 15 + "." + "b" * 15 + "." + "c" * 15,
        "-----BEGIN PRIVATE KEY----- synthetic-not-a-key",
        'GITHUB_TOKEN = "synthetic-private-canary"',
        'AWS_SECRET_ACCESS_KEY = "synthetic-private-canary"',
    ],
)
def test_known_credentials_cannot_become_customer_passages_or_titles(synthetic):
    with pytest.raises(ValueError) as failure:
        credential_free_text(synthetic)
    assert synthetic not in str(failure.value)
    with pytest.raises(ValidationError):
        SupportPassage(passage_id="synthetic-passage", text=synthetic)
    with pytest.raises(ValidationError):
        SupportDocument.model_validate(
            {
                "source_id": "synthetic-source",
                "title": synthetic,
                "approval": "approved_customer_safe",
                "passages": [{"passage_id": "synthetic-passage", "text": "Public help copy."}],
            }
        )


def test_credential_screen_does_not_apply_user_email_filter_to_public_copy():
    public = "Contact the public help desk at help@example.test."
    assert credential_free_text(public) == public
    assert SupportPassage(passage_id="public-contact", text=public).text == public
    # This reusable credential screen does not invent a URL ban. PassageText's
    # existing plain-text URL policy remains independently enforced unchanged.
    reference = public + " Public help: https://help.example.test/faq."
    assert credential_free_text(reference) == reference
    with pytest.raises(ValueError):
        public_ai_question(public)


def test_existing_approved_corpus_identities_and_copy_are_unchanged():
    package = load_corpus_package()
    assert len(package.documents) == 9
    assert sum(len(document.passages) for document in package.documents) == 19
    assert support_corpus_digest(package) == (
        "1fa44fda7549fcac866926c07c56c9778deaa8e29955309b1f8bab80c24f5063"
    )
    assert package.document_digests == {
        document.source_id: support_document_digest(document.document())
        for document in package.documents
    }
