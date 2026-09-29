CREATE TABLE IF NOT EXISTS drafts (
    id TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL CHECK (entity_type IN ('document', 'term', 'source', 'taxonomy')),
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

CREATE TABLE IF NOT EXISTS proposals (
    id TEXT PRIMARY KEY,
    target_type TEXT NOT NULL CHECK (target_type IN ('document', 'term', 'source', 'taxonomy')),
    target_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN (
        'metadata', 'link', 'new_term', 'term_revision',
        'document_revision', 'taxonomy', 'evidence', 'format'
    )),
    status TEXT NOT NULL CHECK (status IN (
        'proposed', 'drafted', 'approved', 'merged', 'rejected', 'stale'
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
    UNIQUE (candidate_type, normalized_value, scope)
);

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
