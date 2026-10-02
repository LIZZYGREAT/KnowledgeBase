"""Canonical Collection metadata and its ordered reference tree."""

from __future__ import annotations

from typing import Annotated, Literal, Optional, Union

from pydantic import Field, conint, model_validator

from .common import CanonicalModel, NonEmptyText, Slug


class EntityNode(CanonicalModel):
    id: Slug
    kind: Literal["entity"]
    entity_type: Literal["document", "term", "source"]
    entity_id: Slug


class SectionNode(CanonicalModel):
    id: Slug
    kind: Literal["section"]
    title: NonEmptyText
    children: list["CollectionNode"] = Field(default_factory=list)


CollectionNode = Annotated[Union[SectionNode, EntityNode], Field(discriminator="kind")]
SectionNode.model_rebuild(_types_namespace={"CollectionNode": CollectionNode})


class Collection(CanonicalModel):
    schema_version: Literal[1]
    id: Slug
    title: NonEmptyText
    description: Optional[NonEmptyText] = None
    status: Literal["active", "archived"]
    position: conint(strict=True, ge=0)
    nodes: list[CollectionNode] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_tree(self) -> "Collection":
        node_ids: set[str] = set()
        entity_refs: set[tuple[str, str]] = set()

        def visit(nodes: list[CollectionNode], section_depth: int = 0) -> None:
            for node in nodes:
                if node.id in node_ids:
                    raise ValueError("Collection node IDs must be unique")
                node_ids.add(node.id)

                if isinstance(node, SectionNode):
                    depth = section_depth + 1
                    if depth > 2:
                        raise ValueError("Collection sections may be nested at most 2 levels deep")
                    visit(node.children, depth)
                    continue

                reference = (node.entity_type, node.entity_id)
                if reference in entity_refs:
                    raise ValueError(
                        "An entity may appear only once in a Collection: {} '{}'".format(*reference)
                    )
                entity_refs.add(reference)

        visit(self.nodes)
        return self
