import pytest

from backend.app.services.ai_client import AIResponseError, MockDeepSeekClient
from backend.app.services.ai_gateway import AIGateway


def test_evidence_suggestion_recommends_source_without_locator_or_quote():
    candidate = {
        "source_id": "source-alpha",
        "claim": "Claim from the Draft",
        "rationale": "The Source metadata appears relevant.",
    }
    result = AIGateway(
        MockDeepSeekClient({"suggest_evidence": {"candidates": [candidate]}})
    ).run("suggest_evidence", {})
    assert result.model_dump() == {"candidates": [candidate]}

    for unsupported_field in ("locator", "quote"):
        invalid = {"candidates": [{**candidate, unsupported_field: "Page 5"}]}
        with pytest.raises(AIResponseError, match="JSON schema"):
            AIGateway(MockDeepSeekClient({"suggest_evidence": invalid})).run(
                "suggest_evidence", {}
            )
