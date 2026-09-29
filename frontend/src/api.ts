export type EntityType = "document" | "term" | "source";

export interface EntitySummary {
  id: string;
  title: string;
  entity_type: EntityType;
  metadata: Record<string, unknown>;
}

export interface EntityDetail extends EntitySummary {
  content: string | null;
  canonical_content: string | null;
  related_terms: EntitySummary[];
  backlinks: Array<Record<string, unknown>>;
  detected_mentions: Array<{ id: string; title: string }>;
  evidence: EvidenceItem[];
  related_documents: EntitySummary[];
}

export interface EvidenceItem {
  source_id: string;
  locator: string | null;
  line: number;
  citation: string;
  claim: string;
  entity_type?: string;
  entity_id?: string;
}

export interface SearchResult {
  entity_type: EntityType;
  entity_id: string;
  title: string;
  matched_by: string;
  score: number;
  snippet: string;
  metadata: Record<string, unknown>;
  view_count: number;
  search_click_count: number;
}

export interface TaxonomyEntry {
  id: string;
  title: string;
  kind: "domain" | "topic" | "tag";
}

export interface UsageDocument {
  entity_id: string;
  title: string;
  view_count: number;
  search_click_count: number;
  last_viewed_at: string | null;
}

export interface Proposal {
  id: string;
  target_type: string;
  target_id: string;
  kind: string;
  status: string;
  base_content_hash: string;
  payload: Record<string, unknown>;
  diff_text: string | null;
  created_by: string;
  provider: string | null;
  model: string | null;
  created_at: string;
  reviewed_at: string | null;
  review_note: string | null;
}

export interface ImportJob {
  id: string;
  status: string;
  profile: string;
  created_at: string;
  updated_at: string;
  error_message: string | null;
  items: Array<{
    id: string;
    display_name: string;
    file_type: "markdown" | "pdf";
    status: string;
    detected_entity_type: string | null;
  }>;
}

export interface LinkIssue {
  document_id: string;
  document_title: string;
  target: string;
  line: number;
  status: "unresolved" | "ambiguous";
  candidate_ids: string[];
}

export interface SearchFilters {
  query: string;
  domain?: string;
  topic?: string;
  tag?: string;
  document_type?: string;
  review?: string;
  maintenance?: string;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...init?.headers,
    },
  });
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const body = (await response.json()) as { detail?: string };
      if (body.detail) message = body.detail;
    } catch {
      // Keep the HTTP status when the server does not return JSON.
    }
    throw new Error(message);
  }
  return (await response.json()) as T;
}

export function getEntity(type: EntityType, id: string) {
  return request<EntityDetail>(`/api/${typePath(type)}/${encodeURIComponent(id)}`);
}

export function listEntities(type: EntityType, offset = 0) {
  return request<EntitySummary[]>(`/api/${typePath(type)}?limit=100&offset=${offset}`);
}

export async function listAllEntities(type: EntityType): Promise<EntitySummary[]> {
  const all: EntitySummary[] = [];
  let offset = 0;
  for (;;) {
    const page = await listEntities(type, offset);
    all.push(...page);
    if (page.length < 100) return all;
    offset += page.length;
  }
}

export function listRecentlyModified(limit = 8) {
  return request<Array<EntitySummary & { modified_at: string }>>(
    `/api/documents/recently-modified?limit=${limit}`,
  );
}

export function listTaxonomy(kind: TaxonomyEntry["kind"]) {
  return request<TaxonomyEntry[]>(`/api/taxonomy?kind=${kind}`);
}

export function listLinkIssues() {
  return request<LinkIssue[]>("/api/review/link-issues");
}

export function listUsage(kind: "recent" | "frequent", limit = 8) {
  return request<UsageDocument[]>(`/api/usage/${kind}?limit=${limit}`);
}

export function searchKnowledge(filters: SearchFilters) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value) params.set(key, value);
  }
  return request<SearchResult[]>(`/api/search?${params.toString()}`);
}

export function listProposals(status: string) {
  return request<Proposal[]>(`/api/proposals?status=${encodeURIComponent(status)}&limit=100`);
}

export function listImports() {
  return request<ImportJob[]>("/api/imports?limit=50");
}

export async function recordSearchClick(documentId: string) {
  return request("/api/usage/search-click", {
    method: "POST",
    body: JSON.stringify({ document_id: documentId }),
  });
}

export async function recordDocumentOpen(documentId: string) {
  return request("/api/usage/document-open", {
    method: "POST",
    body: JSON.stringify({ document_id: documentId }),
  });
}

function typePath(type: EntityType) {
  return type === "document" ? "documents" : `${type}s`;
}
