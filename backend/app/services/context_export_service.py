"""Assemble trust-filtered context from indexed canonical knowledge."""

import json
import sqlite3
from typing import Optional

from backend.app.services.knowledge_read_service import KnowledgeReadService
from backend.app.services.markdown_parser import parse_markdown
from backend.app.services.resolution import normalize_key


class ContextExportService:
    def __init__(self, knowledge: KnowledgeReadService, connection: sqlite3.Connection):
        self.knowledge = knowledge
        self.connection = connection

    def export(
        self,
        document_id: Optional[str] = None,
        source_id: Optional[str] = None,
        trust: str = "raw",
        purpose: str = "research",
    ) -> dict:
        if bool(document_id) == bool(source_id):
            raise ValueError("Provide exactly one of document_id or source_id")
        if trust not in {"raw", "reviewed", "verified"}:
            raise ValueError("trust must be raw, reviewed, or verified")
        if purpose not in {"research", "teaching", "evidence"}:
            raise ValueError("purpose must be research, teaching, or evidence")

        selected_source = self.knowledge.get_entity("source", source_id) if source_id else None
        selected_document = self.knowledge.get_entity("document", document_id) if document_id else None
        if selected_document:
            related_documents = self._related_documents_for_document(selected_document)
            source_ids = selected_document["metadata"].get("sources", [])
            source_ids.extend(item["source_id"] for item in selected_document["evidence"])
        else:
            related_documents = selected_source["related_documents"]
            source_ids = [source_id]
        related_documents = related_documents[:20]
        document_details = [
            self.knowledge.get_entity("document", item["id"])
            for item in related_documents
        ]
        if selected_document and selected_document["id"] not in {
            document["id"] for document in document_details
        }:
            document_details.insert(0, selected_document)

        for document in document_details:
            source_ids.extend(document["metadata"].get("sources", []))
            source_ids.extend(item["source_id"] for item in document["evidence"])
        source_ids = sorted(set(source_ids))
        sources = []
        for current_id in source_ids:
            try:
                source = self.knowledge.get_entity("source", current_id)
            except LookupError:
                continue
            if trust != "verified" or _source_verified(source):
                sources.append({"id": source["id"], "title": source["title"], "metadata": source["metadata"]})
        source_map = {source["id"]: source for source in sources}

        documents = []
        terms_by_id = {}
        claims = []
        evidence = []
        ambiguities = []
        for document in document_details:
            approved = _human_approved(document["metadata"])
            if trust == "reviewed" and not approved:
                continue
            rows = self._document_evidence(document["id"])
            verified_rows = [
                row for row in rows
                if approved and row["source_id"] in source_map
                and _source_verified(source_map[row["source_id"]])
            ]
            if trust == "verified" and not verified_rows:
                continue
            value = {
                "id": document["id"],
                "title": document["title"],
                "metadata": document["metadata"],
                "human_review": _human_review_status(document["metadata"]),
            }
            if trust == "raw" or (trust == "reviewed" and approved):
                value["content"] = document["content"]
            documents.append(value)
            allowed_rows = rows if trust == "raw" else verified_rows if trust == "verified" else rows
            for row in allowed_rows:
                claims.append({
                    "document_id": document["id"],
                    "document_title": document["title"],
                    "claim": row["claim"],
                    "source_id": row["source_id"],
                    "locator": row["locator"],
                    "line": row["line"],
                    "citation": row["citation"],
                })
                evidence.append({
                    "document_id": document["id"],
                    "source_id": row["source_id"],
                    "locator": row["locator"],
                    "line": row["line"],
                    "citation": row["citation"],
                })
            if trust != "verified" or verified_rows:
                ambiguities.extend(self._ambiguities(document))
            if purpose != "evidence":
                for term in document["related_terms"]:
                    term_detail = self.knowledge.get_entity("term", term["id"])
                    if trust == "reviewed" and not _human_approved(term_detail["metadata"]):
                        continue
                    terms_by_id[term_detail["id"]] = {
                        "id": term_detail["id"],
                        "title": term_detail["title"],
                        "metadata": term_detail["metadata"],
                        "definition": term_detail["content"],
                    }

        if purpose == "evidence":
            documents = []
            terms_by_id = {}
        if trust == "verified":
            documents = [
                {key: value for key, value in document.items() if key != "content"}
                for document in documents
            ]
        return {
            "scope": {"document_id": document_id} if document_id else {"source_id": source_id},
            "trust": trust,
            "purpose": purpose,
            "sources": sources,
            "documents": documents,
            "terms": list(terms_by_id.values()),
            "claims": claims,
            "evidence": evidence,
            "known_ambiguities": _deduplicate(ambiguities),
        }

    def _related_documents_for_document(self, document: dict) -> list[dict]:
        source_ids = list(document["metadata"].get("sources", []))
        source_ids.extend(item["source_id"] for item in document["evidence"])
        if not source_ids:
            return [{"id": document["id"], "title": document["title"], "metadata": document["metadata"]}]
        records = []
        for source_id in source_ids:
            source = self.knowledge.get_entity("source", source_id)
            records.extend(source["related_documents"])
        by_id = {record["id"]: record for record in records}
        by_id[document["id"]] = {
            "id": document["id"], "title": document["title"], "metadata": document["metadata"]
        }
        return [by_id[entity_id] for entity_id in sorted(by_id)]

    def _document_evidence(self, document_id: str) -> list[dict]:
        rows = self.connection.execute(
            """SELECT source_id, locator, line, citation, claim
               FROM evidence_index WHERE entity_type = 'document' AND entity_id = ?
               ORDER BY line, source_id""",
            (document_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def _ambiguities(self, document: dict) -> list[dict]:
        parsed = parse_markdown(document["content"] or "")
        term_rows = self.connection.execute("SELECT entity_id, title, aliases_json FROM term_index").fetchall()
        known = {}
        for row in term_rows:
            for value in [row["entity_id"], row["title"]] + json.loads(row["aliases_json"]):
                key = normalize_key(value)
                known.setdefault(key, set()).add(row["entity_id"])
        result = []
        for link in parsed.wiki_links:
            candidates = known.get(normalize_key(link.target), set())
            if len(candidates) != 1:
                result.append({
                    "document_id": document["id"],
                    "target": link.target,
                    "line": link.line,
                    "status": "unresolved" if not candidates else "ambiguous",
                    "candidate_ids": sorted(candidates),
                })
        return result


def _human_review_status(metadata: dict) -> str:
    return ((metadata.get("review") or {}).get("human") or {}).get("status", "unreviewed")


def _human_approved(metadata: dict) -> bool:
    return _human_review_status(metadata) == "approved"


def _source_verified(source: dict) -> bool:
    review = source["metadata"].get("metadata_review") or {}
    return review.get("status") == "verified"


def _deduplicate(items: list[dict]) -> list[dict]:
    unique = {(item["document_id"], item["target"], item["line"]): item for item in items}
    return [unique[key] for key in sorted(unique)]
