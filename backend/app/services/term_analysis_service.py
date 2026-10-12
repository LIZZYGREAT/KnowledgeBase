"""Analyze canonical Documents for reusable Terms and persist reviewed Candidates."""

import asyncio
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

from backend.app.domain.ai import DetectTermsOutput
from backend.app.domain.document import DocumentMetadata
from backend.app.domain.term_runtime import TermCandidateEvidenceInput
from backend.app.repositories.term_candidate_repository import TermCandidateRepository
from backend.app.services.ai_client import AIResponseError
from backend.app.services.markdown_parser import parse_markdown
from backend.app.services.resolution import normalize_key
from backend.app.services.term_candidate_service import (
    TermCandidateConflict,
    TermCandidateService,
)
from backend.app.services.term_registry import TermRegistry
from backend.app.services.term_resolver import TermResolver


PROMPT_VERSION = "term-detection-v3"
MAX_ANALYSIS_WARNINGS = 10


class TermAnalysisConflict(RuntimeError):
    """Raised when a canonical Document cannot be safely analyzed or reviewed."""


class _InvalidDetectionCandidate(ValueError):
    """A single model item failed a deterministic candidate-level check."""


class TermAnalysisService:
    def __init__(
        self,
        repository_root: Path,
        candidate_repository: TermCandidateRepository,
        candidate_service: TermCandidateService,
        ai_gateway,
        draft_service,
        canonical_target_resolver,
    ):
        self.repository_root = Path(repository_root).resolve()
        self.candidate_repository = candidate_repository
        self.candidate_service = candidate_service
        self.ai_gateway = ai_gateway
        self.draft_service = draft_service
        self.canonical_target_resolver = canonical_target_resolver

    async def analyze_document(self, document_id: str) -> dict:
        canonical_path = self.canonical_target_resolver.resolve_existing_target_path(
            "document", document_id
        )
        if canonical_path is None:
            raise LookupError("Canonical Document '{}' does not exist".format(document_id))

        active_drafts = self.draft_service.list_for_target("document", document_id)
        if active_drafts:
            raise TermAnalysisConflict(
                "Term Analysis uses canonical content. This Document has an unpublished Draft; "
                "publish or discard it before analysis."
            )

        canonical_bytes = canonical_path.read_bytes()
        canonical_content = canonical_bytes.decode("utf-8")
        parsed = parse_markdown(canonical_content)
        if parsed.frontmatter is None or parsed.frontmatter_end_line is None:
            raise ValueError("Canonical Document '{}' has invalid frontmatter".format(document_id))
        metadata = DocumentMetadata.model_validate(parsed.frontmatter)
        if metadata.id != document_id:
            raise ValueError("Canonical Document id does not match the requested id")

        lines = canonical_content.lstrip("\ufeff").splitlines()
        body = "\n".join(lines[parsed.frontmatter_end_line :]).strip()
        content_hash = sha256(canonical_bytes).hexdigest()
        registry = TermRegistry.load(self.repository_root / "knowledge" / "terms")
        current_scope = "origin:document:{}".format(document_id)
        context = {
            "document": {
                "id": metadata.id,
                "title": metadata.title,
                "type": metadata.type,
                "domains": metadata.domains,
                "topics": metadata.topics,
                "canonical_body": body,
            },
            "term_registry": [
                {
                    "id": term.id,
                    "title": term.title,
                    "aliases": term.aliases,
                    "type": term.type,
                    "depth": term.depth,
                }
                for term in registry.terms
            ],
            "reject_context": {
                "global": self.candidate_repository.rejected_names(["global"]),
                "current_origin": self.candidate_repository.rejected_names(
                    [current_scope]
                ),
            },
        }
        result = await asyncio.to_thread(self.ai_gateway.run, "detect_terms", context)
        if not isinstance(result, DetectTermsOutput):
            result = DetectTermsOutput.model_validate(result)

        resolver = TermResolver(registry)
        terms_by_id = {term.id: term for term in registry.terms}
        counts = {
            "created_candidates": 0,
            "reused_candidates": 0,
            "existing": 0,
            "new": 0,
            "skipped": 0,
            "invalid_candidates": 0,
        }
        validated_items = []
        invalid_warnings = []
        for index, item in enumerate(result.candidates, start=1):
            try:
                normalized_name = normalize_key(item.mention)
                if not normalized_name:
                    raise _InvalidDetectionCandidate("mention 不包含可检索文本")
                if item.mention not in body or item.context_excerpt not in body:
                    raise _InvalidDetectionCandidate(
                        "mention 或 context_excerpt 不在 Canonical 正文中"
                    )
                if item.mention not in item.context_excerpt:
                    raise _InvalidDetectionCandidate(
                        "context_excerpt 不包含完整 mention"
                    )
                if item.action == "link_existing" and item.term_id not in terms_by_id:
                    raise _InvalidDetectionCandidate("引用了未知 Term ID")
                registry_match = resolver.resolve(item.mention)
                if item.action == "link_existing" and (
                    registry_match.status == "resolved"
                    and registry_match.entity_id != item.term_id
                ):
                    raise _InvalidDetectionCandidate(
                        "Existing 关联与服务端 Term 解析结果冲突"
                    )
                validated_items.append((item, registry_match, normalized_name))
            except _InvalidDetectionCandidate as error:
                counts["invalid_candidates"] += 1
                invalid_warnings.append(
                    "候选 {} 已舍弃：{}。".format(index, error)
                )

        if result.candidates and not validated_items:
            first_diagnostic = invalid_warnings[0] if invalid_warnings else "候选结构无效。"
            raise AIResponseError(
                "All Term detection candidates were discarded as invalid ({}): {}".format(
                    counts["invalid_candidates"], first_diagnostic
                )
            )

        warnings = invalid_warnings[:MAX_ANALYSIS_WARNINGS]
        if len(invalid_warnings) > MAX_ANALYSIS_WARNINGS:
            warnings[-1] = "另有 {} 条无效候选未逐条列出。".format(
                len(invalid_warnings) - MAX_ANALYSIS_WARNINGS + 1
            )

        for item, registry_match, normalized_name in validated_items:
            resolved_term = terms_by_id.get(registry_match.entity_id or "")
            effective_existing_term_id = (
                registry_match.entity_id
                if registry_match.status == "resolved"
                else item.term_id
                if item.action == "link_existing"
                else None
            )
            if self.candidate_repository.has_accepted_candidate_evidence(
                normalized_name, "document", document_id
            ) or (
                effective_existing_term_id is not None
                and self.candidate_repository.has_relation(
                    "document", document_id, effective_existing_term_id
                )
            ):
                counts["skipped"] += 1
                continue
            if self.candidate_repository.is_rejected(normalized_name, "global") or (
                self.candidate_repository.is_rejected(normalized_name, current_scope)
            ):
                counts["skipped"] += 1
                continue

            ai_term = terms_by_id.get(item.term_id or "")
            suggested_type = (
                resolved_term.type
                if resolved_term is not None
                else ai_term.type
                if ai_term is not None
                else item.suggested_type
            )
            if suggested_type is None:
                raise AIResponseError(
                    "Term detection needs a suggested_type when the mention does not resolve to an existing Term"
                )

            had_open_candidate = (
                self.candidate_repository.find_open_candidate(normalized_name) is not None
            )
            evidence = TermCandidateEvidenceInput(
                origin_type="document",
                origin_id=document_id,
                mention=item.mention,
                context_excerpt=item.context_excerpt,
                confidence=item.confidence,
                rationale=item.rationale,
            )
            try:
                candidate = self.candidate_service.create_candidate(
                    item.mention,
                    suggested_type,
                    [evidence],
                    preferred_term_id=(
                        item.term_id if item.action == "link_existing" else None
                    ),
                )
            except TermCandidateConflict:
                counts["skipped"] += 1
                continue
            if had_open_candidate:
                counts["reused_candidates"] += 1
            else:
                counts["created_candidates"] += 1
            if candidate.suggested_term_id:
                counts["existing"] += 1
            else:
                counts["new"] += 1

        analyzed_at = _utc_now()
        state = {
            "document_id": document_id,
            "analyzed_content_hash": content_hash,
            "prompt_version": PROMPT_VERSION,
            "provider": self.ai_gateway.provider,
            "model": self.ai_gateway.model,
            "analyzed_at": analyzed_at,
        }
        self.candidate_repository.save_document_analysis_state(state)
        return {
            **state,
            "status": "up_to_date",
            "statistics": counts,
            "warnings": warnings,
        }

    def get_document_analysis_state(self, document_id: str) -> dict:
        canonical_path = self.canonical_target_resolver.resolve_existing_target_path(
            "document", document_id
        )
        if canonical_path is None:
            raise LookupError("Canonical Document '{}' does not exist".format(document_id))
        content = canonical_path.read_bytes()
        current_hash = sha256(content).hexdigest()
        state = self.candidate_repository.get_document_analysis_state(document_id)
        if state is None:
            return {
                "document_id": document_id,
                "status": "never_analyzed",
                "analyzed_content_hash": None,
                "prompt_version": None,
                "provider": None,
                "model": None,
                "analyzed_at": None,
            }
        status = (
            "up_to_date"
            if state["analyzed_content_hash"] == current_hash
            and state["prompt_version"] == PROMPT_VERSION
            else "outdated"
        )
        return {**state, "status": status}

    def get_library_analysis_statuses(self, documents: list[dict]) -> dict[str, str]:
        """Compare indexed canonical hashes to analysis records in bounded SQL batches."""
        states = self.candidate_repository.list_document_analysis_states(
            [document["id"] for document in documents]
        )
        result = {}
        for document in documents:
            document_id = document["id"]
            state = states.get(document_id)
            if state is None:
                status = "never_analyzed"
            elif (
                state["analyzed_content_hash"] == document["content_hash"]
                and state["prompt_version"] == PROMPT_VERSION
            ):
                status = "up_to_date"
            else:
                status = "outdated"
            result[document_id] = status
        return result


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
