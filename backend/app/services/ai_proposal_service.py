"""Build limited context and persist validated AI results as Proposals."""

import asyncio
from hashlib import sha256
from pathlib import Path
from typing import Optional

import yaml
from pydantic import ValidationError

from backend.app.domain.document import DocumentMetadata
from backend.app.domain.source import SourceMetadata
from backend.app.domain.taxonomy import TaxonomyRegistry as TaxonomyRegistryModel
from backend.app.domain.term import TermMetadata
from backend.app.services.ai_client import AIGatewayError, AIResponseError
from backend.app.services.ai_gateway import AIGateway, TASKS
from backend.app.services.markdown_parser import parse_markdown, parse_yaml
from backend.app.services.proposal_service import ProposalService
from backend.app.services.resolution import normalize_key
from backend.app.services.source_registry import SourceRegistry
from backend.app.services.style_linter import load_writing_standard
from backend.app.services.taxonomy_registry import TaxonomyRegistry
from backend.app.services.term_registry import TermRegistry
from backend.app.services.term_language import replace_term_language


class AIProposalService:
    """Build minimal registry context and persist only validated AI output."""

    def __init__(self, repository_root: Path, draft_service, proposal_service: ProposalService, gateway: AIGateway):
        self.repository_root = Path(repository_root).resolve()
        self.draft_service = draft_service
        self.proposal_service = proposal_service
        self.gateway = gateway

    def generate(self, task_name: str, draft_id: str, extra_context: Optional[dict] = None):
        task, draft, registries, context = self._prepare(task_name, draft_id, extra_context)
        cached = self._cached_term_proposal(task_name, draft)
        if cached is not None:
            return cached
        result = self.gateway.run(task_name, context)
        return self._persist_result(task, draft, registries, result, extra_context)

    async def generate_async(
        self, task_name: str, draft_id: str, extra_context: Optional[dict] = None
    ):
        task, draft, registries, context = self._prepare(task_name, draft_id, extra_context)
        cached = self._cached_term_proposal(task_name, draft)
        if cached is not None:
            return cached
        result = await asyncio.to_thread(self.gateway.run, task_name, context)
        return self._persist_result(task, draft, registries, result, extra_context)

    def _cached_term_proposal(self, task_name, draft):
        if task_name != "draft_term":
            return None
        content_hash = sha256(draft.content.encode("utf-8")).hexdigest()
        for proposal in self.proposal_service.list(target_type="term", target_id=draft.entity_id, kind="new_term", status="proposed"):
            if proposal.base_content_hash == content_hash and proposal.payload.get("draft_id") == draft.id and proposal.payload.get("task") == task_name:
                return proposal
        return None

    def _prepare(self, task_name: str, draft_id: str, extra_context: Optional[dict]):
        task = TASKS.get(task_name)
        if task is None:
            raise ValueError("Unsupported AI task: {}".format(task_name))
        if task.output_usage != "proposal" or task.proposal_kind is None:
            raise ValueError("AI task '{}' does not produce a Proposal".format(task_name))
        draft = self.draft_service.get(draft_id)
        if extra_context is not None and not isinstance(extra_context, dict):
            raise ValueError("AI request context must be a JSON object")
        registries = self._registries(task.registry_context)
        context = {
            "target": {"type": draft.entity_type, "id": draft.entity_id},
            "draft": {"id": draft.id, "revision": draft.revision, "content": draft.content},
            "registries": registries,
            "request": extra_context or {},
        }
        return task, draft, registries, context

    def _persist_result(
        self, task, draft, registries: dict, result, request_context: Optional[dict] = None
    ):
        task_name = task.name
        result_data = result.model_dump(mode="json", exclude_none=True)
        term_candidate = (request_context or {}).get("term_candidate")
        if task_name == "draft_term" and term_candidate:
            if result_data["type"] != term_candidate["suggested_type"]:
                raise AIResponseError(
                    "Term Draft output must preserve the Candidate's suggested type"
                )
            if result_data["depth"] == "deep":
                raise AIResponseError(
                    "Note Candidates cannot receive an automatic deep Term Draft"
                )
            candidate_name = term_candidate.get("display_name", "").strip()
            aliases = result_data.setdefault("aliases", [])
            alias_keys = {normalize_key(alias) for alias in aliases}
            if (
                normalize_key(candidate_name)
                and normalize_key(candidate_name) != normalize_key(result_data["title"])
                and normalize_key(candidate_name) not in alias_keys
            ):
                aliases.append(candidate_name)
        try:
            self._validate_result(task_name, draft, result_data, registries)
        except AIGatewayError:
            raise
        except (ValidationError, ValueError) as error:
            raise AIResponseError("AI proposal content failed canonical schema validation") from error

        payload = {"task": task_name, "draft_id": draft.id, "result": result_data}
        proposed_content = result_data.get("proposed_content")
        if isinstance(proposed_content, str):
            payload["content"] = proposed_content
        if task_name == "draft_term":
            payload["content"] = self._term_markdown(result_data)
        if task_name == "rewrite_term_language":
            if draft.entity_type != "term":
                raise AIResponseError("Term rewrite requires a Term Draft")
            payload["content"] = replace_term_language(draft.content, (request_context or {}).get("language"), result_data["explanation"])

        base_hash = sha256(draft.content.encode("utf-8")).hexdigest()
        return self.proposal_service.create(
            target_type=draft.entity_type,
            target_id=draft.entity_id,
            kind=task.proposal_kind,
            base_content_hash=base_hash,
            payload=payload,
            created_by="ai",
            provider=self.gateway.provider,
            model=self.gateway.model,
            base_content=draft.content if "content" in payload else None,
            proposed_content=payload.get("content"),
        )

    def _registries(self, requested: tuple[str, ...]) -> dict:
        result = {}
        knowledge = self.repository_root / "knowledge"
        if "terms" in requested:
            registry = TermRegistry.load(knowledge / "terms")
            result["terms"] = [
                {"id": term.id, "title": term.title, "aliases": term.aliases, "type": term.type}
                for term in registry.terms
            ]
        if "taxonomy" in requested:
            registry = TaxonomyRegistry.load(knowledge / "taxonomy")
            result["taxonomy"] = {
                kind: [
                    {"id": record.entry.id, "title": record.entry.title,
                     "aliases": list(record.entry.aliases)}
                    for record in registry.records if record.kind == kind
                ]
                for kind in ("domain", "topic", "tag")
            }
        if "sources" in requested:
            registry = SourceRegistry.load(knowledge / "sources")
            result["sources"] = [
                {"id": source.id, "title": source.title, "type": source.type,
                 "authors": source.authors, "year": source.year,
                 "identifiers": source.identifiers.model_dump(exclude_none=True)}
                for source in registry.sources
            ]
        if "writing_standard" in requested:
            standard = load_writing_standard(self.repository_root / "config" / "writing-standard.yaml")
            result["writing_standard"] = standard.model_dump(mode="json")
        return result

    def _validate_result(self, task_name: str, draft, result: dict, registries: dict) -> None:
        if task_name == "draft_term":
            if draft.entity_type != "term" or result["id"] != draft.entity_id:
                raise AIResponseError("Term Draft output must match the target Term Draft id")
        if task_name == "suggest_metadata":
            changes = result["changes"]
            for field, kind in (("domains", "domain"), ("topics", "topic"), ("tags", "tag")):
                known = {entry["id"] for entry in registries["taxonomy"][kind]}
                unknown = set(changes.get(field, [])) - known
                if unknown:
                    raise AIResponseError(
                        "Metadata suggestion contains unknown {} id(s): {}".format(
                            kind, ", ".join(sorted(unknown))
                        )
                    )
            known_sources = {source["id"] for source in registries["sources"]}
            unknown_sources = set(changes.get("sources", [])) - known_sources
            if unknown_sources:
                raise AIResponseError(
                    "Metadata suggestion contains unknown Source id(s): {}".format(
                        ", ".join(sorted(unknown_sources))
                    )
                )
        if task_name == "suggest_evidence":
            known = {source["id"] for source in registries["sources"]}
            unknown = {candidate["source_id"] for candidate in result["candidates"]} - known
            if unknown:
                raise AIResponseError(
                    "Evidence suggestion contains unknown Source id(s): {}".format(
                        ", ".join(sorted(unknown))
                    )
                )
        if "proposed_content" in result:
            content = result["proposed_content"]
            if draft.entity_type in {"document", "term"}:
                parsed = parse_markdown(content)
                if parsed.frontmatter is None:
                    raise AIResponseError("Proposed Markdown must have valid YAML frontmatter")
                entity = (
                    DocumentMetadata.model_validate(parsed.frontmatter)
                    if draft.entity_type == "document"
                    else TermMetadata.model_validate(parsed.frontmatter)
                )
                if entity.id != draft.entity_id:
                    raise AIResponseError("Proposed Markdown id must match the target Draft")
            elif draft.entity_type == "source":
                entity = SourceMetadata.model_validate(parse_yaml(content))
                if entity.id != draft.entity_id:
                    raise AIResponseError("Proposed Source id must match the target Draft")
            elif draft.entity_type == "taxonomy":
                TaxonomyRegistryModel.model_validate(parse_yaml(content))

    @staticmethod
    def _term_markdown(result: dict) -> str:
        metadata = {
            "schema_version": 1,
            "id": result["id"],
            "title": result["title"],
            "type": result["type"],
            "depth": result["depth"],
            "aliases": result.get("aliases", []),
            "domains": [],
            "topics": [],
            "tags": [],
            "sources": [],
            "provenance": {"origin": "human-authored", "ai_assisted": True},
        }
        frontmatter = yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False).rstrip()
        content = "---\n{}\n---\n# {}\n".format(frontmatter, result["title"])
        if result.get("definition_zh") or result.get("definition_en"):
            for language in ("zh", "en"):
                if result.get("definition_" + language):
                    content = replace_term_language(content, language, result["definition_" + language])
        else:
            content += "\n" + result["definition"].strip() + "\n"
        return content
