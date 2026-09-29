from hashlib import sha256

import pytest

from backend.app.db.connection import connect_database
from backend.app.repositories.annotation_repository import AnnotationRepository
from backend.app.services.presentation_annotation_service import (
    AnnotationConflictError,
    PresentationAnnotationService,
)


def _create(service, content, selected, start, style_type="highlight", style_value="yellow"):
    return service.create(
        entity_type="document",
        entity_id="reader-note",
        style_type=style_type,
        style_value=style_value,
        selected_text=selected,
        prefix_text="",
        suffix_text="",
        start_offset=start,
        end_offset=start + len(selected.encode("utf-16-le")) // 2,
        base_content_hash=sha256(content.encode("utf-8")).hexdigest(),
        content=content,
    )


@pytest.fixture
def annotation_service():
    connection = connect_database(":memory:")
    try:
        yield PresentationAnnotationService(AnnotationRepository(connection))
    finally:
        connection.close()


def test_annotation_is_runtime_only_upserts_style_and_deletes(annotation_service):
    content = "A useful phrase remains in the canonical body."
    initial = _create(annotation_service, content, "useful phrase", 2)
    recolored = _create(annotation_service, content, "useful phrase", 2, "highlight", "green")
    text_color = _create(annotation_service, content, "useful phrase", 2, "text_color", "blue")

    assert initial.id == recolored.id
    assert recolored.style_value == "green"
    assert text_color.id != initial.id
    assert text_color.style_type == "text_color"
    assert text_color.style_value == "blue"
    assert len(annotation_service.list_for_entity("document", "reader-note", content)) == 2

    annotation_service.delete(recolored.id)
    annotation_service.delete(text_color.id)
    assert annotation_service.list_for_entity("document", "reader-note", content) == []


def test_offsets_use_browser_utf16_units(annotation_service):
    content = "A 🧠 idea"
    annotation = _create(annotation_service, content, "🧠", 2)

    assert annotation.start_offset == 2
    assert annotation.end_offset == 4
    assert annotation.selected_text == "🧠"


def test_changed_content_reanchors_unique_text_and_context(annotation_service):
    original = "left mark right"
    annotation = _create(annotation_service, original, "mark", 5)

    moved = annotation_service.list_for_entity(
        "document", "reader-note", "new opening\nleft mark right"
    )

    assert moved[0].status == "active"
    assert moved[0].start_offset == len("new opening\nleft ")


def test_ambiguous_changed_content_becomes_stale(annotation_service):
    original = "one mark two"
    annotation = _create(annotation_service, original, "mark", 4)

    stale = annotation_service.list_for_entity(
        "document", "reader-note", "one mark two\none mark two"
    )

    assert stale[0].id == annotation.id
    assert stale[0].status == "stale"


def test_invalid_palette_anchor_and_content_hash_are_rejected(annotation_service):
    content = "reader annotation"
    with pytest.raises(ValueError, match="palette"):
        _create(annotation_service, content, "reader", 0, "highlight", "#ff00ff")
    with pytest.raises(ValueError, match="range"):
        _create(annotation_service, content, "other", 0)
    with pytest.raises(AnnotationConflictError, match="Canonical content changed"):
        annotation_service.create(
            entity_type="term",
            entity_id="reader-term",
            style_type="underline",
            style_value=None,
            selected_text="reader",
            prefix_text="",
            suffix_text="",
            start_offset=0,
            end_offset=6,
            base_content_hash="0" * 64,
            content=content,
        )
