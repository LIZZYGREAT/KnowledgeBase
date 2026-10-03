"""Build a bounded Research Context Pack from pinned and retrieved knowledge."""

from dataclasses import dataclass
import html
import re
from typing import Any, Optional, Sequence

from backend.app.domain.research import ResearchProfile, ResearchLens
from backend.app.domain.research_runtime import (
    ResearchContextCard,
    ResearchContextPack,
    ResearchContextSection,
    ResearchWorkRecord,
)
from backend.app.services.collection_service import CollectionService
from backend.app.services.context_export_service import ContextExportService
from backend.app.services.knowledge_read_service import KnowledgeReadService
from backend.app.services.research_deduplicator import normalize_title
from backend.app.services.search_service import SearchResult, SearchService


_MAX_SEARCH_QUERY_LENGTH = 2_000
_MAX_RETRIEVAL_QUERIES = 12
_MAX_EXCERPT_LENGTH = 450
_MAX_SECTIONS_PER_CARD = 2
_QUERY_STOPWORDS = frozenset(
    "a an and are as at be by for from in into is it of on or that the to with".split()
)
_QUERY_TOKEN_PATTERN = re.compile(
    r"[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)*|"
    r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uac00-\ud7af]+"
)
_CJK_TOKEN_PATTERN = re.compile(
    r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uac00-\ud7af]"
)


@dataclass(frozen=True)
class _ContextCandidate:
    card: ResearchContextCard
    review_rank: int


class ResearchContextBuilder:
    def __init__(
        self,
        knowledge: KnowledgeReadService,
        collections: CollectionService,
        context_export: ContextExportService,
        max_context_entities: int,
    ):
        if (
            isinstance(max_context_entities, bool)
            or not isinstance(max_context_entities, int)
            or max_context_entities < 1
        ):
            raise ValueError("max_context_entities must be a positive integer")
        self.knowledge = knowledge
        self.collections = collections
        self.context_export = context_export
        self.search = SearchService(knowledge.connection)
        self.max_context_entities = max_context_entities

    def build(
        self,
        work: ResearchWorkRecord,
        profile: ResearchProfile,
        matched_lens: ResearchLens,
        keywords: tuple[str, ...] = (),
    ) -> ResearchContextPack:
        canonical_lens = next(
            (lens for lens in profile.lenses if lens.id == matched_lens.id), None
        )
        if canonical_lens is None or canonical_lens != matched_lens:
            raise ValueError("Matched Lens does not belong to the Research Profile")

        focus_query = _focus_query(work, matched_lens, keywords)
        focus_tokens = set(normalize_title(focus_query).split())
        candidates: dict[tuple[str, str], _ContextCandidate] = {}

        for collection_id in profile.context.collections:
            collection = self.collections.get_collection(collection_id)
            collection_sections, entities = _collection_context(collection)
            collection_metadata = {
                "status": collection["status"],
                "position": collection["position"],
            }
            if collection.get("description"):
                collection_sections.insert(
                    0,
                    ResearchContextSection(
                        heading="Collection",
                        excerpt=_clean_excerpt(collection["description"]),
                    ),
                )
            self._offer(
                candidates,
                entity_type="collection",
                entity_id=collection_id,
                title=collection["title"],
                metadata=collection_metadata,
                pinned=True,
                retrieval_score=0.0,
                sections=tuple(collection_sections[:_MAX_SECTIONS_PER_CARD]),
                topics=(),
                domains=(),
                review_status="not_applicable",
            )
            for entity_type, entity_id in entities:
                self._offer_canonical_entity(
                    candidates,
                    entity_type,
                    entity_id,
                    pinned=True,
                    retrieval_score=0.0,
                    search_result=None,
                    focus_query=focus_query,
                    focus_tokens=focus_tokens,
                )

        for document_id in profile.context.documents:
            self._offer_canonical_entity(
                candidates,
                "document",
                document_id,
                pinned=True,
                retrieval_score=0.0,
                search_result=None,
                focus_query=focus_query,
                focus_tokens=focus_tokens,
            )

        if profile.context.dynamic_retrieval.enabled:
            for result in self._dynamic_search_results(work, matched_lens, keywords):
                self._offer_canonical_entity(
                    candidates,
                    result.entity_type,
                    result.entity_id,
                    pinned=False,
                    retrieval_score=float(result.score),
                    search_result=result,
                    focus_query=focus_query,
                    focus_tokens=focus_tokens,
                )

        ordered = sorted(
            candidates.values(),
            key=lambda item: (
                -item.review_rank,
                -int(item.card.pinned),
                -item.card.retrieval_score,
                item.card.title.casefold(),
                item.card.entity_type,
                item.card.entity_id,
            ),
        )
        selected = tuple(item.card for item in ordered[: self.max_context_entities])
        return ResearchContextPack(
            focus_query=focus_query,
            cards=selected,
            budget=self.max_context_entities,
            omitted_count=max(0, len(ordered) - len(selected)),
        )

    def _dynamic_search_results(
        self,
        work: ResearchWorkRecord,
        matched_lens: ResearchLens,
        keywords: tuple[str, ...],
    ) -> list[SearchResult]:
        """Run several short searches because SearchService ANDs query tokens."""
        result_limit = min(100, max(20, self.max_context_entities * 10))
        best_by_entity: dict[tuple[str, str], SearchResult] = {}
        for query in _retrieval_queries(work, matched_lens, keywords):
            for result in self.search.search(query=query, limit=result_limit):
                key = (result.entity_type, result.entity_id)
                previous = best_by_entity.get(key)
                if (
                    previous is None
                    or _search_result_rank(result) < _search_result_rank(previous)
                ):
                    best_by_entity[key] = result

        ordered = sorted(
            best_by_entity.values(),
            key=lambda result: (
                -result.score,
                -_match_priority(result.matched_by),
                result.title.casefold(),
                result.entity_type,
                result.entity_id,
            ),
        )
        return ordered[:result_limit]

    def _offer_canonical_entity(
        self,
        candidates: dict[tuple[str, str], _ContextCandidate],
        entity_type: str,
        entity_id: str,
        pinned: bool,
        retrieval_score: float,
        search_result: Optional[SearchResult],
        focus_query: str,
        focus_tokens: set[str],
    ) -> None:
        entity = self.knowledge.get_entity(entity_type, entity_id)
        metadata = entity["metadata"]
        review_status = _review_status(entity_type, metadata)
        sections = self._relevant_sections(
            entity_type,
            entity_id,
            entity.get("content") or "",
            metadata,
            search_result,
            focus_query,
            focus_tokens,
        )
        card_metadata = _card_metadata(entity_type, metadata)
        self._offer(
            candidates,
            entity_type=entity_type,
            entity_id=entity_id,
            title=entity["title"],
            metadata=card_metadata,
            pinned=pinned,
            retrieval_score=retrieval_score,
            sections=sections,
            topics=_string_tuple(metadata.get("topics")),
            domains=_string_tuple(metadata.get("domains")),
            review_status=review_status,
        )

    def _relevant_sections(
        self,
        entity_type: str,
        entity_id: str,
        content: str,
        metadata: dict,
        search_result: Optional[SearchResult],
        focus_query: str,
        focus_tokens: set[str],
    ) -> tuple[ResearchContextSection, ...]:
        sections: list[ResearchContextSection] = []
        if search_result is not None and search_result.snippet:
            heading = "Evidence" if search_result.matched_by == "evidence" else "Relevant passage"
            sections.append(
                ResearchContextSection(
                    heading=heading,
                    excerpt=_clean_excerpt(search_result.snippet),
                )
            )

        if entity_type == "document" and (search_result is None or search_result.matched_by == "evidence"):
            evidence = self.context_export.export(
                document_id=entity_id,
                trust="raw",
                purpose="evidence",
            )
            sections.extend(
                _evidence_sections(
                    evidence.get("claims", []),
                    focus_tokens,
                    document_id=entity_id,
                )
            )
        elif entity_type == "source" and search_result is None:
            evidence = self.context_export.export(
                source_id=entity_id,
                trust="raw",
                purpose="evidence",
            )
            sections.extend(_evidence_sections(evidence.get("claims", []), focus_tokens))

        if not sections and entity_type in {"document", "term"}:
            sections.extend(_extract_content_sections(content, focus_query))
        if not sections and entity_type == "source":
            excerpt = _source_excerpt(metadata)
            if excerpt:
                sections.append(
                    ResearchContextSection(heading="Source metadata", excerpt=excerpt)
                )
        return _deduplicate_sections(sections)[:_MAX_SECTIONS_PER_CARD]

    def _offer(
        self,
        candidates: dict[tuple[str, str], _ContextCandidate],
        entity_type: str,
        entity_id: str,
        title: str,
        metadata: dict[str, Any],
        pinned: bool,
        retrieval_score: float,
        sections: tuple[ResearchContextSection, ...],
        topics: tuple[str, ...],
        domains: tuple[str, ...],
        review_status: str,
    ) -> None:
        key = (entity_type, entity_id)
        previous = candidates.get(key)
        if previous is not None:
            sections = _deduplicate_sections(
                list(previous.card.relevant_sections) + list(sections)
            )[:_MAX_SECTIONS_PER_CARD]
            pinned = pinned or previous.card.pinned
            retrieval_score = max(retrieval_score, previous.card.retrieval_score)
            if not metadata:
                metadata = previous.card.metadata
            topics = topics or previous.card.topics
            domains = domains or previous.card.domains
            review_status = (
                previous.card.review_status
                if _review_rank(previous.card.review_status) > _review_rank(review_status)
                else review_status
            )

        card = ResearchContextCard(
            entity_type=entity_type,
            entity_id=entity_id,
            title=title,
            review_status=review_status,
            topics=topics,
            domains=domains,
            relevant_sections=sections,
            metadata=metadata,
            pinned=pinned,
            retrieval_score=float(retrieval_score),
        )
        candidates[key] = _ContextCandidate(card, _review_rank(review_status))


def _focus_query(
    work: ResearchWorkRecord, matched_lens, keywords: tuple[str, ...]
) -> str:
    pieces = [work.title, work.abstract or "", *keywords, *matched_lens.include_terms]
    normalized_parts = []
    seen = set()
    for piece in pieces:
        text = " ".join(str(piece).split())
        if text and text.casefold() not in seen:
            seen.add(text.casefold())
            normalized_parts.append(text)
    return " ".join(normalized_parts)[:_MAX_SEARCH_QUERY_LENGTH]


def _retrieval_queries(
    work: ResearchWorkRecord,
    matched_lens: ResearchLens,
    keywords: tuple[str, ...],
) -> tuple[str, ...]:
    """Generate a bounded set of short, discriminating lexical searches."""
    queries: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        query = " ".join(str(value).split()).strip()
        key = query.casefold()
        if query and key not in seen and len(queries) < _MAX_RETRIEVAL_QUERIES:
            seen.add(key)
            queries.append(query)

    # Profile terms and extracted keywords are the most intentional retrieval hints.
    for value in (*keywords, *matched_lens.include_terms):
        if len(value.split()) <= 4:
            add(value)

    # Break the Work's title and abstract into compact lexical windows. SearchService
    # applies AND semantics to each query, so sending the whole Work would usually
    # produce no matches.
    for value in (work.title, work.abstract or ""):
        for sentence in re.split(r"(?<=[.!?;:。！？；：])\s*", value):
            tokens = _QUERY_TOKEN_PATTERN.findall(sentence)
            terms = [
                token
                for token in tokens
                if token.casefold() not in _QUERY_STOPWORDS
                and (len(token) > 2 or _CJK_TOKEN_PATTERN.search(token))
            ]
            for width in (3, 2):
                for start in range(max(0, len(terms) - width + 1)):
                    add(" ".join(terms[start : start + width]))
            if len(terms) == 1:
                add(terms[0])
            if len(queries) >= _MAX_RETRIEVAL_QUERIES:
                break
        if len(queries) >= _MAX_RETRIEVAL_QUERIES:
            break
    return tuple(queries)


def _match_priority(matched_by: str) -> int:
    return {
        "exact id": 5,
        "title": 4,
        "alias": 3,
        "full text": 2,
        "evidence": 1,
        "browse": 0,
    }.get(matched_by, -1)


def _search_result_rank(result: SearchResult) -> tuple[float, int, int, str]:
    return (
        -result.score,
        -_match_priority(result.matched_by),
        -len(result.snippet),
        result.title.casefold(),
    )


def _collection_context(collection: dict) -> tuple[list[ResearchContextSection], list[tuple[str, str]]]:
    sections = []
    entities = []
    entries = []

    def visit(nodes, breadcrumbs=()):
        for node in nodes:
            if node["kind"] == "section":
                visit(node["children"], breadcrumbs + (node["title"],))
            else:
                entity_type = node["entity_type"]
                entity_id = node["entity_id"]
                entities.append((entity_type, entity_id))
                path = " / ".join(breadcrumbs)
                entries.append(
                    "{}{} ({})".format(
                        path + ": " if path else "",
                        node["title"],
                        entity_type,
                    )
                )

    visit(collection["nodes"])
    if entries:
        excerpt = "; ".join(entries[:6])
        if len(entries) > 6:
            excerpt += "; and {} more".format(len(entries) - 6)
        sections.append(
            ResearchContextSection(
                heading="Pinned members",
                excerpt=_clean_excerpt(excerpt),
            )
        )
    return sections, entities


def _review_status(entity_type: str, metadata: dict) -> str:
    if entity_type == "source":
        status = (metadata.get("metadata_review") or {}).get("status")
        return status if isinstance(status, str) and status.strip() else "unreviewed"
    status = ((metadata.get("review") or {}).get("human") or {}).get("status")
    return status if isinstance(status, str) and status.strip() else "unreviewed"


def _review_rank(status: str) -> int:
    if status in {"approved", "verified"}:
        return 2
    if status in {"reviewed", "needs_attention"}:
        return 1
    if status in {"rejected", "unverified"}:
        return -1
    return 0


def _card_metadata(entity_type: str, metadata: dict) -> dict[str, Any]:
    if entity_type in {"document", "term"}:
        return {
            key: metadata[key]
            for key in ("type", "tags", "aliases")
            if key in metadata
        }
    if entity_type == "source":
        return {
            key: metadata[key]
            for key in ("type", "authors", "year", "identifiers", "url")
            if key in metadata
        }
    return {}


def _evidence_sections(
    claims: list[dict], focus_tokens: set[str], document_id: Optional[str] = None
) -> list[ResearchContextSection]:
    matches = []
    for claim in claims:
        if document_id is not None and claim.get("document_id") != document_id:
            continue
        text = _clean_excerpt(claim.get("claim", ""))
        if not text:
            continue
        overlap = len(set(normalize_title(text).split()) & focus_tokens)
        if overlap:
            heading = "Evidence"
            if claim.get("document_title"):
                heading += " · {}".format(claim["document_title"])
            if claim.get("line") is not None:
                heading += " · line {}".format(claim["line"])
            matches.append(
                (
                    -overlap,
                    claim.get("line", 0),
                    ResearchContextSection(heading=heading, excerpt=text),
                )
            )
    matches.sort(key=lambda item: (item[0], item[1], item[2].excerpt))
    return [item[2] for item in matches[:_MAX_SECTIONS_PER_CARD]]


def _extract_content_sections(content: str, focus_query: str) -> list[ResearchContextSection]:
    lines = content.splitlines()
    parsed: list[tuple[str, list[str], int]] = []
    heading = "Overview"
    body: list[str] = []
    order = 0
    for line in lines:
        match = re.match(r"^#{1,6}\s+(.+?)\s*#*\s*$", line.strip())
        if match:
            if body:
                parsed.append((heading, body, order))
                order += 1
            heading = _clean_excerpt(match.group(1)) or "Section"
            body = []
        else:
            body.append(line)
    if body:
        parsed.append((heading, body, order))
    if not parsed and content.strip():
        parsed.append(("Overview", [content], 0))

    focus_tokens = set(normalize_title(focus_query).split())
    scored = []
    for section_heading, section_lines, order in parsed:
        text = _clean_excerpt(" ".join(section_lines))
        if not text:
            continue
        tokens = set(normalize_title(section_heading + " " + text).split())
        overlap = len(tokens & focus_tokens)
        scored.append((-overlap, order, section_heading, text))
    scored.sort(key=lambda item: (item[0], item[1]))
    selected = [item for item in scored if item[0] < 0][:_MAX_SECTIONS_PER_CARD]
    if not selected:
        selected = scored[:1]
    return [
        ResearchContextSection(heading=heading, excerpt=excerpt)
        for _, _, heading, excerpt in selected
    ]


def _source_excerpt(metadata: dict) -> str:
    details = []
    authors = metadata.get("authors") or []
    if authors:
        details.append("Authors: {}".format(", ".join(str(author) for author in authors[:8])))
    if metadata.get("year") is not None:
        details.append("Year: {}".format(metadata["year"]))
    identifiers = metadata.get("identifiers") or {}
    for key in ("doi", "arxiv_id"):
        if identifiers.get(key):
            details.append("{}: {}".format(key, identifiers[key]))
    return _clean_excerpt("; ".join(details))


def _clean_excerpt(value: str) -> str:
    text = html.unescape(value or "")
    text = re.sub(r"</?mark>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"[`*_~>#]", "", text)
    text = " ".join(text.split())
    if len(text) > _MAX_EXCERPT_LENGTH:
        text = text[: _MAX_EXCERPT_LENGTH - 1].rstrip() + "…"
    return text


def _deduplicate_sections(
    sections: Sequence[ResearchContextSection]
) -> list[ResearchContextSection]:
    unique = {}
    for section in sections:
        key = (section.heading, section.excerpt)
        unique.setdefault(key, section)
    return [unique[key] for key in unique]


def _string_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(item for item in value if isinstance(item, str) and item.strip())[:12]
