"""Read and track progress through canonical Collection trees."""

from datetime import datetime, timezone
from pathlib import Path
import sqlite3

from backend.app.domain.collection import Collection, EntityNode, SectionNode
from backend.app.services.collection_registry import CollectionRegistry


_ENTITY_INDEX_TABLES = {
    "document": "document_index",
    "term": "term_index",
    "source": "source_index",
}


class CollectionService:
    """Resolve Collection references without mixing them into entity reads."""

    def __init__(self, repository_root: Path, connection: sqlite3.Connection):
        self.repository_root = Path(repository_root).resolve()
        self.collections_root = self.repository_root / "knowledge" / "collections"
        self.connection = connection

    def list_collections(self, status: str = "active") -> list[dict]:
        collections = CollectionRegistry.load(self.collections_root).collections
        if status not in {"active", "archived"}:
            raise ValueError("Collection status must be active or archived")
        visible = [collection for collection in collections if collection.status == status]
        visible.sort(key=lambda item: (item.position, item.title.casefold(), item.id))
        return [self._summary(collection) for collection in visible]

    def get_collection(self, collection_id: str) -> dict:
        collection = self._get_model(collection_id)
        progress = {
            row["document_id"]: row["status"]
            for row in self.connection.execute(
                "SELECT document_id, status FROM collection_progress WHERE collection_id = ?",
                (collection_id,),
            ).fetchall()
        }
        return {
            "id": collection.id,
            "title": collection.title,
            "description": collection.description,
            "status": collection.status,
            "position": collection.position,
            "nodes": [self._node_view(node, progress) for node in collection.nodes],
        }

    def navigation(self, collection_id: str, entity_type: str, entity_id: str) -> dict:
        collection = self._get_model(collection_id)
        ordered = []

        def visit(nodes, sections=()):
            for node in nodes:
                if isinstance(node, SectionNode):
                    visit(node.children, sections + (node.title,))
                elif isinstance(node, EntityNode):
                    ordered.append(
                        {
                            "entity_type": node.entity_type,
                            "entity_id": node.entity_id,
                            "title": self._entity_title(node.entity_type, node.entity_id),
                            "breadcrumbs": list(sections),
                        }
                    )

        visit(collection.nodes)
        current_index = next(
            (
                index
                for index, item in enumerate(ordered)
                if item["entity_type"] == entity_type and item["entity_id"] == entity_id
            ),
            None,
        )
        if current_index is None:
            raise ValueError(
                "{} '{}' is not a member of Collection '{}'".format(
                    entity_type, entity_id, collection_id
                )
            )
        current = ordered[current_index]
        return {
            "collection_id": collection.id,
            "collection_title": collection.title,
            "breadcrumbs": current["breadcrumbs"],
            "previous": ordered[current_index - 1] if current_index > 0 else None,
            "next": ordered[current_index + 1] if current_index + 1 < len(ordered) else None,
        }

    def set_progress(self, collection_id: str, document_id: str, status: str) -> dict:
        if status not in {"reading", "done"}:
            raise ValueError("Progress status must be reading or done")
        collection = self._get_model(collection_id)
        if not any(
            node.entity_type == "document" and node.entity_id == document_id
            for node in _entity_nodes(collection.nodes)
        ):
            raise ValueError(
                "Document '{}' is not a member of Collection '{}'".format(
                    document_id, collection_id
                )
            )
        updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self.connection:
            self.connection.execute(
                """INSERT INTO collection_progress (collection_id, document_id, status, updated_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(collection_id, document_id) DO UPDATE SET
                       status = excluded.status, updated_at = excluded.updated_at""",
                (collection_id, document_id, status, updated_at),
            )
        return {
            "collection_id": collection_id,
            "document_id": document_id,
            "status": status,
            "updated_at": updated_at,
        }

    def _get_model(self, collection_id: str) -> Collection:
        collection = CollectionRegistry.load(self.collections_root).get(collection_id)
        if collection is None:
            raise LookupError("Collection '{}' does not exist".format(collection_id))
        return collection

    def _summary(self, collection: Collection) -> dict:
        nodes = list(_all_nodes(collection.nodes))
        entity_nodes = [node for node in nodes if isinstance(node, EntityNode)]
        return {
            "id": collection.id,
            "title": collection.title,
            "description": collection.description,
            "status": collection.status,
            "position": collection.position,
            "node_count": len(nodes),
            "entity_count": len(entity_nodes),
            "document_count": sum(node.entity_type == "document" for node in entity_nodes),
        }

    def _node_view(self, node, progress: dict) -> dict:
        if isinstance(node, SectionNode):
            return {
                "id": node.id,
                "kind": "section",
                "title": node.title,
                "children": [self._node_view(child, progress) for child in node.children],
            }
        return {
            "id": node.id,
            "kind": "entity",
            "entity_type": node.entity_type,
            "entity_id": node.entity_id,
            "title": self._entity_title(node.entity_type, node.entity_id),
            "progress": progress.get(node.entity_id) if node.entity_type == "document" else None,
        }

    def _entity_title(self, entity_type: str, entity_id: str) -> str:
        table = _ENTITY_INDEX_TABLES[entity_type]
        row = self.connection.execute(
            "SELECT title FROM {} WHERE entity_id = ?".format(table), (entity_id,)
        ).fetchone()
        return row["title"] if row is not None else entity_id


def _all_nodes(nodes):
    for node in nodes:
        yield node
        if isinstance(node, SectionNode):
            yield from _all_nodes(node.children)


def _entity_nodes(nodes):
    for node in nodes:
        if isinstance(node, EntityNode):
            yield node
        elif isinstance(node, SectionNode):
            yield from _entity_nodes(node.children)
