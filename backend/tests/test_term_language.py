from backend.app.domain.ai import DraftTermOutput
from backend.app.services.ai_proposal_service import AIProposalService
from backend.app.services.markdown_parser import parse_markdown
from backend.app.services.term_language import replace_term_language


def test_bilingual_generation_and_single_language_rewrite_preserve_other_section():
    output = DraftTermOutput(id="ewc", title="EWC", type="concept", depth="stub",
                            definition_zh="EWC 使用 Fisher Information。", definition_en="EWC uses Fisher Information.")
    text = AIProposalService._term_markdown(output.model_dump(exclude_none=True))
    updated = replace_term_language(text, "zh", "EWC 约束重要参数。")
    assert "## 一、中文解释" in updated and "## 二、English Explanation" in updated
    assert "EWC uses Fisher Information." in updated
    assert "EWC 使用 Fisher Information。" not in updated
    assert parse_markdown(text).frontmatter == parse_markdown(updated).frontmatter


def test_language_boundaries_ignore_fenced_code_and_keep_old_content():
    original = "# EWC\n\nOriginal explanation.\n\n```markdown\n## 一、中文解释\n```\n"
    updated = replace_term_language(original, "en", "English definition.")
    assert original.strip() in updated
    assert "## 一、English Explanation" in updated
    assert "```markdown\n## 一、中文解释\n```" in updated


def test_single_language_and_original_definition_remain_valid():
    for explanation in ({"definition_en": "Only English."}, {"definition": "Original body."}):
        output = DraftTermOutput(id="ewc", title="EWC", type="concept", depth="stub", **explanation)
        text = AIProposalService._term_markdown(output.model_dump(exclude_none=True))
        assert next(iter(explanation.values())) in text
