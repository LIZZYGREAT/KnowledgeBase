CREATE TABLE IF NOT EXISTS drafts (
    id TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL CHECK (entity_type IN (
        'document', 'term', 'source', 'taxonomy', 'collection', 'research_profile'
    )),
    entity_id TEXT NOT NULL,
    base_git_revision TEXT NOT NULL,
    base_content_hash TEXT NOT NULL,
    content TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision > 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS drafts_target_updated_idx
    ON drafts (entity_type, entity_id, updated_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS drafts_target_unique_idx
    ON drafts (entity_type, entity_id);

CREATE TABLE IF NOT EXISTS proposals (
    id TEXT PRIMARY KEY,
    target_type TEXT NOT NULL CHECK (target_type IN ('document', 'term', 'source', 'taxonomy')),
    target_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN (
        'metadata', 'link', 'new_term', 'term_revision',
        'document_revision', 'taxonomy', 'evidence', 'format'
    )),
    status TEXT NOT NULL CHECK (status IN (
        'proposed', 'drafted', 'merged', 'rejected', 'stale'
    )),
    base_content_hash TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    diff_text TEXT,
    created_by TEXT NOT NULL,
    provider TEXT,
    model TEXT,
    created_at TEXT NOT NULL,
    reviewed_at TEXT,
    review_note TEXT
);

CREATE INDEX IF NOT EXISTS proposals_target_status_idx
    ON proposals (target_type, target_id, status, created_at DESC);

CREATE TABLE IF NOT EXISTS rejected_candidates (
    id TEXT PRIMARY KEY,
    candidate_type TEXT NOT NULL CHECK (candidate_type IN ('term', 'taxonomy')),
    normalized_value TEXT NOT NULL,
    reason TEXT NOT NULL,
    scope TEXT NOT NULL,
    created_at TEXT NOT NULL,
    restored_at TEXT,
    UNIQUE (candidate_type, normalized_value, scope)
);

CREATE TABLE IF NOT EXISTS term_candidates (
    id TEXT PRIMARY KEY,
    normalized_name TEXT NOT NULL,
    display_name TEXT NOT NULL,
    suggested_type TEXT NOT NULL CHECK (
        suggested_type IN ('concept', 'entity', 'vocabulary')
    ),
    suggested_term_id TEXT,
    status TEXT NOT NULL CHECK (
        status IN ('pending', 'drafting', 'accepted', 'rejected')
    ),
    draft_id TEXT,
    accepted_term_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    reviewed_at TEXT,
    recommendation_json TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS term_candidates_open_name_idx
    ON term_candidates (normalized_name)
    WHERE status IN ('pending', 'drafting');
CREATE INDEX IF NOT EXISTS term_candidates_status_idx
    ON term_candidates (status, updated_at DESC);

CREATE TABLE IF NOT EXISTS term_candidate_evidence (
    id TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL,
    origin_type TEXT NOT NULL CHECK (
        origin_type IN ('document', 'source', 'research_work', 'external')
    ),
    origin_id TEXT NOT NULL,
    mention TEXT NOT NULL,
    origin_title TEXT,
    context_excerpt TEXT,
    confidence REAL CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    rationale TEXT,
    discovered_at TEXT NOT NULL,
    FOREIGN KEY (candidate_id) REFERENCES term_candidates(id) ON DELETE CASCADE,
    UNIQUE (candidate_id, origin_type, origin_id, mention)
);
CREATE INDEX IF NOT EXISTS term_candidate_evidence_origin_idx
    ON term_candidate_evidence (origin_type, origin_id);

CREATE TABLE IF NOT EXISTS term_entity_relations (
    id TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL CHECK (
        entity_type IN ('document', 'source', 'research_work')
    ),
    entity_id TEXT NOT NULL,
    term_id TEXT NOT NULL,
    created_from_candidate_id TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (entity_type, entity_id, term_id)
);
CREATE INDEX IF NOT EXISTS term_entity_relations_term_idx
    ON term_entity_relations (term_id, entity_type, entity_id);
CREATE INDEX IF NOT EXISTS term_entity_relations_entity_idx
    ON term_entity_relations (entity_type, entity_id, term_id);

CREATE TABLE IF NOT EXISTS term_merge_history (
    id TEXT PRIMARY KEY,
    loser_term_id TEXT NOT NULL,
    survivor_term_id TEXT NOT NULL,
    merged_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS term_merge_history_survivor_idx
    ON term_merge_history (survivor_term_id, merged_at DESC);

CREATE TABLE IF NOT EXISTS document_term_analysis_state (
    document_id TEXT PRIMARY KEY,
    analyzed_content_hash TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    analyzed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pdf_corpus (
    source_id TEXT PRIMARY KEY,
    pdf_hash TEXT NOT NULL,
    extractor_version TEXT NOT NULL,
    text_hash TEXT,
    text TEXT,
    status TEXT NOT NULL CHECK (
        status IN ('pending', 'ready', 'unavailable', 'failed')
    ),
    extracted_at TEXT,
    error_message TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS corpus_analysis_state (
    source_id TEXT NOT NULL,
    text_hash TEXT NOT NULL,
    focus_hash TEXT NOT NULL,
    analysis_lane TEXT NOT NULL CHECK (
        analysis_lane IN ('concept', 'entity', 'vocabulary')
    ),
    analysis_version INTEGER NOT NULL,
    analyzed_at TEXT NOT NULL,
    PRIMARY KEY (source_id, analysis_lane)
);

CREATE TABLE IF NOT EXISTS vocabulary_source_statistics (
    source_id TEXT NOT NULL,
    normalized_term TEXT NOT NULL,
    display_term TEXT NOT NULL,
    term_count INTEGER NOT NULL CHECK (term_count > 0),
    text_hash TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (source_id, normalized_term)
);
CREATE INDEX IF NOT EXISTS vocabulary_source_statistics_term_idx
    ON vocabulary_source_statistics (normalized_term, source_id);

CREATE TABLE IF NOT EXISTS term_discovery_settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    enabled_lanes_json TEXT NOT NULL,
    quota_json TEXT NOT NULL,
    source_preferences_json TEXT NOT NULL,
    focus_override TEXT,
  external_enabled INTEGER NOT NULL DEFAULT 0 CHECK (external_enabled IN (0, 1)),
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS term_discovery_runs (
    id TEXT PRIMARY KEY,
    trigger TEXT NOT NULL CHECK (trigger IN ('manual', 'scheduled')),
    status TEXT NOT NULL CHECK (
        status IN ('success', 'partial', 'failed', 'skipped_capacity', 'skipped_disabled')
    ),
    snapshot_json TEXT NOT NULL,
    lane_budgets_json TEXT NOT NULL,
    raw_counts_json TEXT NOT NULL,
    filtered_counts_json TEXT NOT NULL,
    candidate_count INTEGER NOT NULL DEFAULT 0 CHECK (candidate_count >= 0),
    started_at TEXT NOT NULL,
    finished_at TEXT,
    error_summary TEXT
);
CREATE INDEX IF NOT EXISTS term_discovery_runs_started_idx
    ON term_discovery_runs (started_at DESC, id);

CREATE TABLE IF NOT EXISTS term_discovery_run_items (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    lane TEXT NOT NULL CHECK (lane IN ('concept', 'entity', 'vocabulary')),
    source_id TEXT NOT NULL,
    mention TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK (
        outcome IN ('created', 'stretch', 'duplicate', 'filtered', 'rejected', 'error')
    ),
    candidate_id TEXT,
    assessment_json TEXT NOT NULL,
    rationale TEXT NOT NULL,
    context_excerpt TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES term_discovery_runs(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS term_discovery_run_items_run_idx
    ON term_discovery_run_items (run_id, lane, created_at, id);

CREATE TABLE IF NOT EXISTS presentation_annotations (
    id TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL CHECK (entity_type IN ('document', 'term')),
    entity_id TEXT NOT NULL,
    style_type TEXT NOT NULL CHECK (style_type IN ('highlight', 'text_color', 'underline')),
    style_value TEXT,
    selected_text TEXT NOT NULL CHECK (length(selected_text) > 0),
    prefix_text TEXT NOT NULL,
    suffix_text TEXT NOT NULL,
    start_offset INTEGER NOT NULL CHECK (start_offset >= 0),
    end_offset INTEGER NOT NULL CHECK (end_offset > start_offset),
    base_content_hash TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('active', 'stale')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK (
        (style_type = 'highlight' AND style_value IS NOT NULL AND style_value IN ('yellow', 'green', 'blue', 'pink', 'gray')) OR
        (style_type = 'text_color' AND style_value IS NOT NULL AND style_value IN ('red', 'orange', 'green', 'blue', 'purple', 'muted')) OR
        (style_type = 'underline' AND style_value IS NULL)
    ),
    UNIQUE (entity_type, entity_id, style_type, start_offset, end_offset)
);

CREATE INDEX IF NOT EXISTS presentation_annotations_entity_idx
    ON presentation_annotations (entity_type, entity_id, start_offset, end_offset);
CREATE INDEX IF NOT EXISTS presentation_annotations_status_idx
    ON presentation_annotations (status, updated_at DESC);

CREATE TABLE IF NOT EXISTS document_index (
    entity_id TEXT PRIMARY KEY,
    path TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    document_type TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    content_hash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS term_index (
    entity_id TEXT PRIMARY KEY,
    path TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    term_type TEXT NOT NULL,
    depth TEXT NOT NULL,
    aliases_json TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    content_hash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS source_index (
    entity_id TEXT PRIMARY KEY,
    path TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    source_type TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    content_hash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS collection_index (
    collection_id TEXT PRIMARY KEY,
    path TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    description TEXT,
    status TEXT NOT NULL CHECK (status IN ('active', 'archived')),
    position INTEGER NOT NULL CHECK (position >= 0),
    content_hash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS collection_node_index (
    collection_id TEXT NOT NULL,
    node_id TEXT NOT NULL,
    parent_node_id TEXT,
    kind TEXT NOT NULL CHECK (kind IN ('section', 'entity')),
    depth INTEGER NOT NULL CHECK (depth >= 0),
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    section_title TEXT,
    entity_type TEXT CHECK (entity_type IN ('document', 'term', 'source')),
    entity_id TEXT,
    PRIMARY KEY (collection_id, node_id),
    FOREIGN KEY (collection_id) REFERENCES collection_index (collection_id) ON DELETE CASCADE,
    CHECK (
        (kind = 'section' AND entity_type IS NULL AND entity_id IS NULL) OR
        (kind = 'entity' AND entity_type IS NOT NULL AND entity_id IS NOT NULL)
    )
);
CREATE INDEX IF NOT EXISTS collection_node_parent_idx
    ON collection_node_index (collection_id, parent_node_id, ordinal);
CREATE INDEX IF NOT EXISTS collection_node_entity_idx
    ON collection_node_index (entity_type, entity_id);

CREATE TABLE IF NOT EXISTS collection_progress (
    collection_id TEXT NOT NULL,
    document_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('reading', 'done')),
    updated_at TEXT NOT NULL,
    PRIMARY KEY (collection_id, document_id)
);

CREATE TABLE IF NOT EXISTS alias_index (
    term_id TEXT NOT NULL,
    alias TEXT NOT NULL,
    normalized_alias TEXT NOT NULL,
    PRIMARY KEY (term_id, normalized_alias)
);
CREATE INDEX IF NOT EXISTS alias_index_normalized_idx
    ON alias_index (normalized_alias, term_id);

CREATE TABLE IF NOT EXISTS taxonomy_index (
    kind TEXT NOT NULL CHECK (kind IN ('domain', 'topic', 'tag')),
    entity_id TEXT NOT NULL,
    title TEXT NOT NULL,
    PRIMARY KEY (kind, entity_id)
);

CREATE TABLE IF NOT EXISTS backlink_index (
    id TEXT PRIMARY KEY,
    source_entity_type TEXT NOT NULL CHECK (source_entity_type IN ('document', 'term')),
    source_entity_id TEXT NOT NULL,
    source_path TEXT NOT NULL,
    term_id TEXT NOT NULL,
    link_target TEXT NOT NULL,
    label TEXT,
    line INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS backlink_target_idx
    ON backlink_index (term_id, source_entity_type, source_entity_id);

CREATE TABLE IF NOT EXISTS evidence_index (
    id TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL CHECK (entity_type IN ('document', 'term')),
    entity_id TEXT NOT NULL,
    entity_path TEXT NOT NULL,
    source_id TEXT NOT NULL,
    locator TEXT,
    line INTEGER NOT NULL,
    citation TEXT NOT NULL,
    claim TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS evidence_source_idx
    ON evidence_index (source_id, entity_type, entity_id);

CREATE VIRTUAL TABLE IF NOT EXISTS document_fts USING fts5(
    entity_id UNINDEXED, title, body, metadata,
    tokenize = 'unicode61 remove_diacritics 2'
);
CREATE VIRTUAL TABLE IF NOT EXISTS term_fts USING fts5(
    entity_id UNINDEXED, title, aliases, body, metadata,
    tokenize = 'unicode61 remove_diacritics 2'
);
CREATE VIRTUAL TABLE IF NOT EXISTS source_fts USING fts5(
    entity_id UNINDEXED, title, metadata,
    tokenize = 'unicode61 remove_diacritics 2'
);
CREATE VIRTUAL TABLE IF NOT EXISTS evidence_fts USING fts5(
    evidence_id UNINDEXED, entity_id UNINDEXED, claim,
    tokenize = 'unicode61 remove_diacritics 2'
);

CREATE TABLE IF NOT EXISTS usage_events (
    id TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL CHECK (entity_type = 'document'),
    entity_id TEXT NOT NULL,
    event_type TEXT NOT NULL CHECK (event_type IN ('document_open', 'search_result_click')),
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS usage_entity_event_idx
    ON usage_events (entity_type, entity_id, event_type, created_at DESC);

CREATE TABLE IF NOT EXISTS document_stats (
    document_id TEXT PRIMARY KEY,
    view_count INTEGER NOT NULL DEFAULT 0 CHECK (view_count >= 0),
    search_click_count INTEGER NOT NULL DEFAULT 0 CHECK (search_click_count >= 0),
    last_viewed_at TEXT
);

CREATE TABLE IF NOT EXISTS import_jobs (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL CHECK (status IN ('staging', 'ready', 'failed')),
    profile TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS import_items (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    path TEXT NOT NULL,
    file_type TEXT NOT NULL CHECK (file_type IN ('markdown', 'pdf')),
    sha256 TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN (
        'ready', 'needs_review', 'duplicate', 'drafted', 'confirmed', 'failed'
    )),
    detected_entity_type TEXT,
    metadata_json TEXT NOT NULL,
    FOREIGN KEY (job_id) REFERENCES import_jobs(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS import_items_job_status_idx
    ON import_items (job_id, status, path);
CREATE INDEX IF NOT EXISTS import_items_hash_idx
    ON import_items (sha256, file_type, status);

CREATE TABLE IF NOT EXISTS research_profile_state (
    profile_id TEXT PRIMARY KEY,
    paused_until TEXT,
    last_successful_scheduled_run_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS research_control_events (
    id TEXT PRIMARY KEY,
    profile_id TEXT NOT NULL,
    event_type TEXT NOT NULL CHECK (
        event_type IN ('pause', 'resume', 'watermark_skip')
    ),
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS research_control_events_profile_idx
    ON research_control_events (profile_id, created_at DESC);

CREATE TABLE IF NOT EXISTS research_works (
    id TEXT PRIMARY KEY,
    canonical_key TEXT NOT NULL,
    title TEXT NOT NULL,
    normalized_title TEXT NOT NULL,
    abstract TEXT,
    authors_json TEXT NOT NULL,
    year INTEGER,
    published_at TEXT,
    venue TEXT,
    doi TEXT,
    arxiv_id TEXT,
    openalex_id TEXT,
    semantic_scholar_id TEXT,
    url TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS research_works_doi_unique
    ON research_works (doi) WHERE doi IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS research_works_arxiv_unique
    ON research_works (arxiv_id) WHERE arxiv_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS research_works_openalex_unique
    ON research_works (openalex_id) WHERE openalex_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS research_works_semantic_scholar_unique
    ON research_works (semantic_scholar_id) WHERE semantic_scholar_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS research_works_normalized_title_idx
    ON research_works (normalized_title, year);

CREATE TABLE IF NOT EXISTS research_discoveries (
    id TEXT PRIMARY KEY,
    work_id TEXT NOT NULL,
    profile_id TEXT NOT NULL,
    lens_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    provider_record_id TEXT NOT NULL,
    query_key TEXT NOT NULL,
    query_text TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    discovered_at TEXT NOT NULL,
    FOREIGN KEY (work_id) REFERENCES research_works(id) ON DELETE CASCADE,
    UNIQUE (profile_id, lens_id, provider, provider_record_id, query_key)
);
CREATE INDEX IF NOT EXISTS research_discoveries_work_idx
    ON research_discoveries (work_id, discovered_at DESC);
CREATE INDEX IF NOT EXISTS research_discoveries_profile_idx
    ON research_discoveries (profile_id, discovered_at DESC);

CREATE TABLE IF NOT EXISTS research_work_analyses (
    id TEXT PRIMARY KEY,
    work_id TEXT NOT NULL,
    profile_id TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK (outcome IN ('surface', 'filtered')),
    analysis_json TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    analysis_version INTEGER NOT NULL,
    context_entity_ids_json TEXT NOT NULL,
    analyzed_at TEXT NOT NULL,
    input_context_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (work_id) REFERENCES research_works(id) ON DELETE CASCADE,
    UNIQUE (work_id, profile_id, input_hash)
);
CREATE INDEX IF NOT EXISTS research_work_analyses_profile_idx
    ON research_work_analyses (profile_id, analyzed_at DESC);

CREATE TABLE IF NOT EXISTS research_candidates (
    id TEXT PRIMARY KEY,
    work_id TEXT NOT NULL,
    profile_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('new', 'shortlisted', 'dismissed', 'saved_source', 'note_created')
    ),
    primary_lens_id TEXT,
    analysis_id TEXT NOT NULL,
    user_note TEXT,
    review_overrides_json TEXT NOT NULL DEFAULT '{}',
    review_revision INTEGER NOT NULL DEFAULT 0,
    dismiss_reason TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    first_viewed_at TEXT,
    last_viewed_at TEXT,
    decided_at TEXT,
    FOREIGN KEY (work_id) REFERENCES research_works(id) ON DELETE CASCADE,
    UNIQUE (work_id, profile_id)
);
CREATE INDEX IF NOT EXISTS research_candidates_inbox_idx
    ON research_candidates (profile_id, status, created_at DESC);

CREATE TABLE IF NOT EXISTS research_search_state (
    profile_id TEXT NOT NULL,
    lens_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    query_key TEXT NOT NULL,
    query_text TEXT NOT NULL,
    completed_through TEXT,
    overlap_floor TEXT,
    history_checkpoint_json TEXT,
    last_attempt_at TEXT,
    last_success_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (profile_id, lens_id, provider, query_key)
);

CREATE TABLE IF NOT EXISTS research_runs (
    id TEXT PRIMARY KEY,
    profile_id TEXT NOT NULL,
    request_id TEXT,
    trigger TEXT NOT NULL CHECK (trigger IN ('scheduled', 'manual')),
    status TEXT NOT NULL CHECK (
        status IN (
            'running', 'success', 'partial', 'failed', 'interrupted',
            'skipped_paused', 'skipped_disabled',
            'skipped_inbox_full', 'capacity_reached'
        )
    ),
    profile_content_hash TEXT NOT NULL,
    effective_config_json TEXT NOT NULL,
    fetched_count INTEGER NOT NULL DEFAULT 0,
    new_work_count INTEGER NOT NULL DEFAULT 0,
    duplicate_count INTEGER NOT NULL DEFAULT 0,
    deterministic_filtered_count INTEGER NOT NULL DEFAULT 0,
    analysis_attempt_count INTEGER NOT NULL DEFAULT 0,
    analyzed_count INTEGER NOT NULL DEFAULT 0,
    analysis_counts_known INTEGER NOT NULL DEFAULT 1,
    surfaced_count INTEGER NOT NULL DEFAULT 0,
    provider_summary_json TEXT NOT NULL,
    error_summary TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT
);
CREATE INDEX IF NOT EXISTS research_runs_profile_idx
    ON research_runs (profile_id, started_at DESC);

CREATE TABLE IF NOT EXISTS research_run_requests (
    id TEXT PRIMARY KEY,
    profile_id TEXT NOT NULL,
    trigger TEXT NOT NULL CHECK (trigger = 'manual'),
    override_json TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'claimed', 'completed', 'failed')),
    created_at TEXT NOT NULL,
    claimed_at TEXT,
    completed_at TEXT
);
CREATE INDEX IF NOT EXISTS research_run_requests_pending_idx
    ON research_run_requests (status, created_at);

CREATE TABLE IF NOT EXISTS research_entity_links (
    id TEXT PRIMARY KEY,
    work_id TEXT NOT NULL,
    entity_type TEXT NOT NULL CHECK (entity_type IN ('source', 'document')),
    entity_id TEXT NOT NULL,
    relation_type TEXT NOT NULL CHECK (relation_type IN ('source', 'note')),
    created_at TEXT NOT NULL,
    UNIQUE (work_id, entity_type, entity_id, relation_type)
);
CREATE INDEX IF NOT EXISTS research_entity_links_work_idx
    ON research_entity_links (work_id);

CREATE TABLE IF NOT EXISTS research_pending_links (
    id TEXT PRIMARY KEY,
    group_id TEXT NOT NULL,
    candidate_id TEXT NOT NULL,
    work_id TEXT NOT NULL,
    draft_id TEXT NOT NULL,
    intended_entity_type TEXT NOT NULL,
    intended_entity_id TEXT NOT NULL,
    relation_type TEXT NOT NULL CHECK (relation_type IN ('source', 'note', 'collection')),
    created_at TEXT NOT NULL,
    UNIQUE (candidate_id, draft_id, relation_type)
);
CREATE INDEX IF NOT EXISTS research_pending_links_group_idx
    ON research_pending_links (group_id);
