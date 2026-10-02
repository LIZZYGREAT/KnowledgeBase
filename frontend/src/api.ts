export type EntityType = "document" | "term" | "source";
export type DraftEntityType = EntityType | "taxonomy" | "collection";
export type AnnotationStyleType = "highlight" | "text_color" | "underline";

export interface PresentationAnnotation {
  id: string;
  entity_type: "document" | "term";
  entity_id: string;
  style_type: AnnotationStyleType;
  style_value: string | null;
  selected_text: string;
  prefix_text: string;
  suffix_text: string;
  start_offset: number;
  end_offset: number;
  base_content_hash: string;
  status: "active" | "stale";
  created_at: string;
  updated_at: string;
}

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

export interface CollectionSummary {
  id: string;
  title: string;
  description: string | null;
  status: "active" | "archived";
  position: number;
  node_count: number;
  entity_count: number;
  document_count: number;
}

export interface CollectionEntityNode {
  id: string;
  kind: "entity";
  entity_type: EntityType;
  entity_id: string;
  title: string;
  progress: "reading" | "done" | null;
}

export interface CollectionSectionNode {
  id: string;
  kind: "section";
  title: string;
  children: CollectionNode[];
}

export type CollectionNode = CollectionEntityNode | CollectionSectionNode;

export interface Collection extends Omit<CollectionSummary, "node_count" | "entity_count" | "document_count"> {
  nodes: CollectionNode[];
}

export interface CollectionNavigationItem {
  entity_type: EntityType;
  entity_id: string;
  title: string;
  breadcrumbs: string[];
}

export interface CollectionNavigation {
  collection_id: string;
  collection_title: string;
  breadcrumbs: string[];
  previous: CollectionNavigationItem | null;
  next: CollectionNavigationItem | null;
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

export interface Draft {
  id: string;
  entity_type: DraftEntityType;
  entity_id: string;
  base_git_revision: string;
  base_content_hash: string;
  content: string;
  revision: number;
  created_at: string;
  updated_at: string;
}

export interface DraftComparison {
  draft: Draft;
  base_content: string;
  current_content: string;
  current_git_revision: string;
  current_content_hash: string;
  canonical_changed: boolean;
}

export interface DraftPreflight {
  draft_id: string;
  valid: boolean;
  conflict: boolean;
  errors: string[];
  warnings: string[];
}

export interface PublishedDraft {
  draft_id: string;
  entity_type: string;
  entity_id: string;
  commit_revision: string;
  proposal_id: string | null;
  warnings: string[];
}

export interface BatchPublishedDrafts {
  results: PublishedDraft[];
  commit_revision: string;
  warnings: string[];
}

export type ContextTrust = "raw" | "reviewed" | "verified";
export type ContextPurpose = "research" | "teaching" | "evidence";
export type ExportedContext = Record<string, unknown> & {
  trust: ContextTrust;
  purpose: ContextPurpose;
};

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
    metadata: Record<string, unknown>;
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
  const isFormData = typeof FormData !== "undefined" && init?.body instanceof FormData;
  const response = await fetch(path, {
    ...init,
    headers: {
      ...(init?.body && !isFormData ? { "Content-Type": "application/json" } : {}),
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
    throw Object.assign(new Error(message), { status: response.status });
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

export function listCollections(status: "active" | "archived" = "active") {
  return request<CollectionSummary[]>(`/api/collections?status=${status}`);
}

export function getCollection(collectionId: string) {
  return request<Collection>(`/api/collections/${encodeURIComponent(collectionId)}`);
}

export function getCollectionNavigation(
  collectionId: string,
  entityType: EntityType,
  entityId: string,
) {
  const params = new URLSearchParams({ entity_type: entityType, entity_id: entityId });
  return request<CollectionNavigation>(
    `/api/collections/${encodeURIComponent(collectionId)}/navigation?${params.toString()}`,
  );
}

export function listUnfiledDocuments(limit = 100, offset = 0) {
  return request<EntitySummary[]>(`/api/library/unfiled?limit=${limit}&offset=${offset}`);
}

export async function listAllUnfiledDocuments(): Promise<EntitySummary[]> {
  const all: EntitySummary[] = [];
  let offset = 0;
  for (;;) {
    const page = await listUnfiledDocuments(100, offset);
    all.push(...page);
    if (page.length < 100) return all;
    offset += page.length;
  }
}

export function updateCollectionProgress(
  collectionId: string,
  documentId: string,
  status: "reading" | "done",
) {
  return request<{
    collection_id: string;
    document_id: string;
    status: "reading" | "done";
    updated_at: string;
  }>(
    `/api/collections/${encodeURIComponent(collectionId)}/progress/${encodeURIComponent(documentId)}`,
    { method: "PUT", body: JSON.stringify({ status }) },
  );
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

export function listProposals(status?: string, targetType?: EntityType, targetId?: string) {
  const params = new URLSearchParams({ limit: "100" });
  if (status) params.set("status", status);
  if (targetType) params.set("target_type", targetType);
  if (targetId) params.set("target_id", targetId);
  return request<Proposal[]>(`/api/proposals?${params.toString()}`);
}

export function listDrafts(entityType: DraftEntityType, entityId: string) {
  const params = new URLSearchParams({ entity_type: entityType, entity_id: entityId });
  return request<Draft[]>(`/api/drafts?${params.toString()}`);
}

export function createDraft(entityType: DraftEntityType, entityId: string, content: string) {
  return request<Draft>("/api/drafts", {
    method: "POST",
    body: JSON.stringify({ entity_type: entityType, entity_id: entityId, content }),
  });
}

export function createBlankDocument(title: string, documentType: "paper-note" | "learning-note" | "course-note", entityId?: string) {
  return request<Draft>("/api/imports/blank-document", {
    method: "POST",
    body: JSON.stringify({ title, document_type: documentType, ...(entityId ? { entity_id: entityId } : {}) }),
  });
}

export function updateDraft(draftId: string, content: string, expectedRevision: number) {
  return request<Draft>(`/api/drafts/${encodeURIComponent(draftId)}`, {
    method: "PUT",
    body: JSON.stringify({ content, expected_revision: expectedRevision }),
  });
}

export function compareDraft(draftId: string) {
  return request<DraftComparison>(`/api/drafts/${encodeURIComponent(draftId)}/compare`);
}

export function preflightDraft(draftId: string) {
  return request<DraftPreflight>(`/api/drafts/${encodeURIComponent(draftId)}/preflight`);
}

export function rebaseDraft(
  draftId: string,
  content: string,
  expectedRevision: number,
  expectedCurrentHash: string,
) {
  return request<Draft>(`/api/drafts/${encodeURIComponent(draftId)}/rebase`, {
    method: "PUT",
    body: JSON.stringify({
      content,
      expected_revision: expectedRevision,
      expected_current_hash: expectedCurrentHash,
    }),
  });
}

export function discardDraft(draftId: string, expectedRevision: number) {
  return request<{ deleted: boolean }>(`/api/drafts/${encodeURIComponent(draftId)}`, {
    method: "DELETE",
    body: JSON.stringify({ expected_revision: expectedRevision }),
  });
}

export function publishDraft(draftId: string) {
  return request<PublishedDraft>("/api/publish", {
    method: "POST",
    body: JSON.stringify({ draft_id: draftId }),
  });
}

export function publishDraftsBatch(draftIds: string[], commitMessage?: string) {
  return request<BatchPublishedDrafts>("/api/publish/batch", {
    method: "POST",
    body: JSON.stringify({ draft_ids: draftIds, commit_message: commitMessage }),
  });
}

export function exportKnowledgeContext(
  type: "document" | "source",
  id: string,
  trust: ContextTrust,
  purpose: ContextPurpose,
) {
  return request<ExportedContext>("/api/context/export", {
    method: "POST",
    body: JSON.stringify({
      ...(type === "document" ? { document_id: id } : { source_id: id }),
      trust,
      purpose,
    }),
  });
}

export function requestAIProposal(
  task: "document-review" | "metadata-suggest" | "selection-review" | "term-draft" | "evidence-suggest",
  draftId: string,
  selection?: string,
) {
  const path = `/api/ai/${task}`;
  return request<{ external_provider_notice: string; proposal: Proposal }>(path, {
    method: "POST",
    body: JSON.stringify({
      draft_id: draftId,
      confirm_deepseek_transfer: true,
      ...(selection ? { selection } : {}),
    }),
  });
}

export function reviewProposal(proposalId: string, action: "approve" | "reject") {
  return request<Proposal>(`/api/proposals/${encodeURIComponent(proposalId)}/${action}`, {
    method: "POST",
    body: JSON.stringify(action === "reject" ? { review_note: "用户拒绝此 Proposal" } : {}),
  });
}

export function listImports() {
  return request<ImportJob[]>("/api/imports?limit=50");
}

export function createImport(paths: string[], profile: "standard" | "legacy") {
  return request<ImportJob>("/api/imports", {
    method: "POST",
    body: JSON.stringify({ paths, profile }),
  });
}

export function uploadImportFiles(files: File[], profile: "standard" | "legacy") {
  const body = new FormData();
  files.forEach((file) => body.append("files[]", file, file.name));
  body.append("profile", profile);
  return request<ImportJob>("/api/imports/upload", { method: "POST", body });
}

export interface ImportItemContent {
  id: string;
  file_type: "markdown" | "pdf";
  status: string;
  content: string | null;
  metadata: Record<string, unknown>;
}

export function getImportItemContent(itemId: string) {
  return request<ImportItemContent>(`/api/import-items/${encodeURIComponent(itemId)}/content`);
}

export function updateImportItem(itemId: string, content: string) {
  return request<{
    id: string;
    status: string;
    metadata: Record<string, unknown>;
  }>(`/api/import-items/${encodeURIComponent(itemId)}`, {
    method: "PUT",
    body: JSON.stringify({ content }),
  });
}

export function createImportDraft(itemId: string) {
  return request<Draft>(`/api/import-items/${encodeURIComponent(itemId)}/draft`, { method: "POST" });
}

export function confirmImportSource(
  itemId: string,
  source: { source_id?: string; title?: string; source_type?: "paper" | "book" | "course" | "web" | "personal" },
) {
  return request<Draft>(`/api/import-items/${encodeURIComponent(itemId)}/confirm-source`, {
    method: "POST",
    body: JSON.stringify(source),
  });
}

export function listPresentationAnnotations(type: "document" | "term", id: string) {
  return request<PresentationAnnotation[]>(
    `/api/annotations?entity_type=${type}&entity_id=${encodeURIComponent(id)}`,
  );
}

export function createPresentationAnnotation(
  annotation: Omit<PresentationAnnotation, "id" | "status" | "created_at" | "updated_at">,
) {
  return request<PresentationAnnotation>("/api/annotations", {
    method: "POST",
    body: JSON.stringify(annotation),
  });
}

export function updatePresentationAnnotation(
  id: string,
  styleType: AnnotationStyleType,
  styleValue: string | null,
) {
  return request<PresentationAnnotation>(`/api/annotations/${encodeURIComponent(id)}`, {
    method: "PUT",
    body: JSON.stringify({ style_type: styleType, style_value: styleValue }),
  });
}

export function deletePresentationAnnotation(id: string) {
  return request<{ deleted: boolean }>(`/api/annotations/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
}

export function listStalePresentationAnnotations() {
  return request<PresentationAnnotation[]>("/api/annotations/stale");
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
