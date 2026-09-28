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
    base_revision TEXT NOT NULL,
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
