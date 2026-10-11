import pytest
from pydantic import ValidationError

from backend.app.domain.ai import DraftTermOutput
from backend.app.domain.runtime import Draft
from backend.app.services.ai_proposal_service import AIProposalService
from backend.app.services.markdown_parser import parse_markdown
from backend.app.services.term_language import replace_term_language


def test_bilingual_generation_and_single_language_rewrite_preserve_other_section():
    output = DraftTermOutput(id="ewc", title="EWC", type="concept", depth="stub",
                            definition_zh="EWC 使用 Fisher Information。", definition_en="EWC uses Fisher Information.")
    content = (
        "---\nschema_version: 1\nid: ewc\ntitle: EWC\ntype: concept\n"
        "depth: stub\naliases: []\ndomains: []\ntopics: []\ntags: []\nsources: []\n---\n"
        "# EWC\n\nUser-authored context outside the language sections.\n"
    )
    draft = Draft("draft-ewc", "term", "ewc", "a" * 40, "b" * 64, content, 1, "now", "now")
    text = AIProposalService._term_markdown(draft, output.model_dump(exclude_none=True))
    updated = replace_term_language(text, "zh", "EWC 约束重要参数。")
    assert "## 一、中文解释" in updated and "## 二、English Explanation" in updated
    assert "EWC uses Fisher Information." in updated
    assert "EWC 使用 Fisher Information。" not in updated
    assert "User-authored context outside the language sections." in updated
    assert parse_markdown(text).frontmatter == parse_markdown(updated).frontmatter


def test_bilingual_generation_preserves_draft_metadata_and_non_language_body():
    content = (
        "---\n"
        "schema_version: 1\n"
        "id: ewc\n"
        "title: Elastic Weight Consolidation\n"
        "type: concept\n"
        "depth: stub\n"
        "aliases: [EWC]\n"
        "domains: [machine-learning]\n"
        "topics: [continual-learning]\n"
        "tags: [regularization]\n"
        "sources: [kirkpatrick-2017]\n"
        "review:\n  human:\n    status: unreviewed\n"
        "provenance:\n  origin: human-authored\n  ai_assisted: false\n"
        "---\n"
        "User note: preserve this sentence.\n\n"
        "## Research note\n\nA hand-written context that is not a language section.\n\n"
        "## 一、中文解释\n\nOld Chinese explanation.\n\n"
        "## 二、English Explanation\n\nOld English explanation.\n"
    )
    draft = Draft("draft-ewc", "term", "ewc", "a" * 40, "b" * 64, content, 1, "now", "now")
    result = {
        "id": "ewc",
        "title": "AI-suggested title must not replace the Draft title",
        "type": "concept",
        "depth": "stub",
        "aliases": ["AI-suggested alias"],
        "definition_zh": "EWC 在持续学习中保护旧任务的重要参数；例如学习新任务时可限制这些参数的变化。",
        "definition_en": "In continual learning, EWC protects parameters important to earlier tasks; for example, it can constrain their changes while learning a new task.",
    }

    updated = AIProposalService._term_markdown(draft, result)
    original = parse_markdown(content)
    parsed = parse_markdown(updated)

    assert parsed.frontmatter == original.frontmatter
    assert parsed.frontmatter_raw == original.frontmatter_raw
    assert "# Elastic Weight Consolidation" in updated
    assert "AI-suggested title must not replace the Draft title" not in updated
    assert "AI-suggested alias" not in updated
    assert "User note: preserve this sentence." in updated
    assert "A hand-written context that is not a language section." in updated
    assert "EWC 在持续学习中保护旧任务的重要参数" in updated
    assert "EWC protects parameters important to earlier tasks" in updated


def test_language_boundaries_ignore_fenced_code_and_keep_old_content():
    original = "# EWC\n\nOriginal explanation.\n\n```markdown\n## 一、中文解释\n```\n"
    updated = replace_term_language(original, "en", "English definition.")
    assert original.strip() in updated
    assert "## 一、English Explanation" in updated
    assert "```markdown\n## 一、中文解释\n```" in updated


def test_bilingual_generation_requires_both_complete_languages():
    with pytest.raises(ValidationError):
        DraftTermOutput.model_validate({
            "id": "ewc",
            "title": "EWC",
            "type": "concept",
            "depth": "stub",
            "definition_zh": "EWC 使用 Fisher Information。",
        })
