from pathlib import Path

from backend.app.db.connection import connect_database
from backend.app.domain.source import SourceMetadata
from backend.app.services.research_history import research_anchor_year, research_history_context, historical_plan
from backend.app.services.source_registry import SourceRegistry
from backend.tests.test_research_runs import _NOW, _profile, _service, FakeProvider


def _write_note(root, identifier="ewc-review", approved=True):
    directory = root / "knowledge" / "documents"
    directory.mkdir(parents=True, exist_ok=True)
    content = Path("backend/tests/fixtures/valid_document.md").read_text(encoding="utf-8")
    content = content.replace("id: ewc-review", "id: " + identifier)
    if not approved:
        content = content.replace("status: approved", "status: unreviewed")
    (directory / (identifier + ".md")).write_text(content, encoding="utf-8")


def test_study_seed_and_earliest_source_do_not_jump_to_a_new_review(tmp_path):
    _write_note(tmp_path)
    path = tmp_path / "knowledge" / "documents" / "ewc-review.md"
    path.write_text(path.read_text(encoding="utf-8").replace("  - ewc-2017", "  - ewc-2017\n  - review-2024"), encoding="utf-8")
    profile = _profile().model_copy(update={"context": _profile().context.model_copy(update={"documents": ["ewc-review"]})})
    sources = SourceRegistry(tuple(SourceMetadata(schema_version=1, id=identifier, title=identifier, type="paper", year=year) for identifier, year in (("ewc-2017", 2017), ("review-2024", 2024))))
    assert research_anchor_year(tmp_path, profile, sources) == 2017
    seeded = profile.model_copy(update={"search": profile.search.model_copy(update={"history_seed_year": 2017})})
    assert research_anchor_year(tmp_path, seeded, SourceRegistry((sources.get("review-2024"),))) == 2017


def test_new_approved_related_knowledge_unlocks_one_year_and_keeps_profile_progress_separate(tmp_path):
    connection = connect_database(":memory:")
    profile = _profile()
    profile = profile.model_copy(update={"search": profile.search.model_copy(update={"history_seed_year": 2017}), "context": profile.context.model_copy(update={"documents": ["ewc-review", "second-note"]})})
    service, runs, repository, client = _service(tmp_path, connection, FakeProvider([]), profile=profile)
    root = service.repository_root
    _write_note(root)
    assert service.run_profile(profile.id).status == "success"
    for _ in range(4):
        assert service.run_profile(profile.id, trigger="manual", manual_incremental=True).status == "success"
    query = service.query_builder.build(profile)[0]
    state = repository.get_state(profile.id, query.lens_id, "arxiv", "history:" + query.query_key)
    assert state.completed_through.startswith("2020-01-01")
    recent = repository.get_state(profile.id, query.lens_id, "arxiv", query.query_key)
    calls = service.providers["arxiv"].calls
    service.run_profile(profile.id, trigger="manual", manual_incremental=True)
    assert service.providers["arxiv"].calls == calls
    _write_note(root, "second-note", approved=False)
    service.run_profile(profile.id, trigger="manual", manual_incremental=True)
    assert service.providers["arxiv"].calls == calls
    _write_note(root, "second-note")
    service.run_profile(profile.id, trigger="manual", manual_incremental=True)
    assert repository.get_state(profile.id, query.lens_id, "arxiv", "history:" + query.query_key).completed_through.startswith("2021-01-01")
    assert repository.get_state(profile.id, query.lens_id, "arxiv", query.query_key) == recent
    service.run_profile(profile.id, trigger="manual", manual_incremental=True)
    assert service.providers["arxiv"].calls == calls + 1
    # An approved Term linked by the approved Note supplies a further learning step.
    term_dir = root / "knowledge" / "terms"
    term_dir.mkdir()
    term = Path("backend/tests/fixtures/valid_term.md").read_text(encoding="utf-8")
    (term_dir / "fisher-information.md").write_text(term.replace("status: unreviewed", "status: approved"), encoding="utf-8")
    service.run_profile(profile.id, trigger="manual", manual_incremental=True)
    assert repository.get_state(profile.id, query.lens_id, "arxiv", "history:" + query.query_key).completed_through.startswith("2022-01-01")
    # Removing/reapproving an already observed entity does not unlock more years.
    _write_note(root, "second-note", approved=False)
    service.run_profile(profile.id, trigger="manual", manual_incremental=True)
    _write_note(root, "second-note")
    service.run_profile(profile.id, trigger="manual", manual_incremental=True)
    assert service.providers["arxiv"].calls == calls + 2
    unrelated = profile.model_copy(update={"id": "other-study", "context": profile.context.model_copy(update={"documents": []}), "title": "Other Study", "lenses": [profile.lenses[0].model_copy(update={"queries": ["unrelated"]})]})
    context = research_history_context(root, unrelated, SourceRegistry(()))
    assert context.approved_ids == ()
    other_query = service.query_builder.build(unrelated)[0]
    plan = historical_plan(repository, unrelated, other_query, "arxiv", 2017, _NOW, context.approved_ids)
    assert plan.slices[0].start_at.year == 2015
    assert plan.history_scope["ceiling_year"] == 2020
    connection.close()


def test_schema18_checkpoint_resumes_and_preserves_cursor_with_new_scope(tmp_path):
    connection = connect_database(":memory:")
    service, _, repository, _ = _service(tmp_path, connection, FakeProvider([]))
    profile = _profile()
    query = service.query_builder.build(profile)[0]
    plan = historical_plan(repository, profile, query, "arxiv", 2017, _NOW)
    service.watermarks.mark_attempt(plan, plan.slices[0], _NOW)
    connection.execute("UPDATE research_search_state SET history_checkpoint_json=?", ('{"start":"2015-01-01T00:00:00+00:00","cursor":"page-two"}',))
    connection.commit()
    resumed = historical_plan(repository, profile, query, "arxiv", 2017, _NOW, ("document:ewc-review",))
    checkpoint = repository.history_checkpoint(profile.id, query.lens_id, "arxiv", plan.query_key)
    assert checkpoint["cursor"] == "page-two"
    assert resumed.slices[0].start_at.year == 2015
    repository.save_history_checkpoint(resumed, resumed.slices[0].start_at, checkpoint["cursor"])
    repository.save_history_checkpoint(resumed, None, None)
    assert repository.history_checkpoint(profile.id, query.lens_id, "arxiv", plan.query_key) is None
    assert repository.history_scope(profile.id, query.lens_id, "arxiv", plan.query_key)["approved_ids"] == ["document:ewc-review"]
    repository.complete_slice(profile.id, query.lens_id, "arxiv", plan.query_key, "2020-01-01T00:00:00+00:00", _NOW.isoformat())
    # A changed bibliographic fallback alone cannot jump an established scope.
    changed_date = historical_plan(repository, profile, query, "arxiv", 2024, _NOW, ("document:ewc-review",))
    assert changed_date.slices == ()
    assert changed_date.history_scope["ceiling_year"] == 2020
    assert connection.execute("PRAGMA user_version").fetchone()[0] == 19
    connection.close()
