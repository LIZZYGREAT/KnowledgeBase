export type EntityType = "document" | "term" | "source";
export type DraftEntityType = EntityType | "taxonomy" | "collection" | "research_profile";
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

export interface ProposalApplyResult {
  proposal: Proposal;
  draft: Draft;
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

export interface ApiError extends Error {
  status: number;
  code?: string;
  expected_revision?: number;
  current_revision?: number;
}

export interface DraftAcquireResult {
  draft: Draft;
  created: boolean;
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

export interface BatchDraftPreflight {
  results: DraftPreflight[];
}

export interface PublishedDraft {
  draft_id: string;
  entity_type: string;
  entity_id: string;
  commit_revision: string;
  warnings: string[];
}

export interface BatchPublishedDrafts {
  results: PublishedDraft[];
  commit_revision: string;
  warnings: string[];
}

export interface DraftPublishExpectation {
  draft_id: string;
  expected_revision: number;
}

export interface PublishOutcome {
  commitRevision: string;
  warnings: string[];
  results: PublishedDraft[];
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

export type ResearchBreadth = "strict" | "balanced" | "explore";
export type ResearchCandidateStatus = "new" | "shortlisted" | "dismissed" | "saved_source" | "note_created";
export type ResearchDismissReason = "not_relevant" | "already_known" | "too_redundant" | "not_interested" | "other";
export type ResearchSort = "recommended" | "newest" | "most_relevant" | "most_novel";

export interface ResearchLens {
  id: string;
  title: string;
  enabled: boolean;
  priority: "low" | "medium" | "high";
  queries: string[];
  include_terms: string[];
  exclude_terms: string[];
}

export interface ResearchProfile {
  schema_version: 1;
  id: string;
  title: string;
  description: string | null;
  enabled: boolean;
  lenses: ResearchLens[];
  exclude_terms: string[];
  providers: { discovery: string[]; enrichment: string[] };
  context: { collections: string[]; documents: string[]; dynamic_retrieval: { enabled: boolean; scope: "entire-library" | "selected-context" } };
  schedule: { mode: "daily" | "weekly" | "manual" };
  search: { breadth: ResearchBreadth; initial_lookback_days: number; max_catchup_days: number; max_candidates_per_run: number; max_analyses_per_run: number };
  inbox: { max_new_candidates: number };
  ai_analysis: { enabled: boolean; provider: "deepseek" };
}

export interface ResearchInboxUsage { new_count: number; capacity: number; remaining: number }
export type ResearchRunStatus = "running" | "success" | "partial" | "failed" | "interrupted" | "skipped_paused" | "skipped_disabled" | "skipped_inbox_full" | "capacity_reached";
export interface ResearchRunSummary {
  id: string;
  trigger: "scheduled" | "manual";
  status: ResearchRunStatus;
  started_at: string;
  finished_at: string | null;
  fetched_count: number;
  surfaced_count: number;
}
export interface ResearchProfileSummary {
  id: string;
  title: string;
  description: string | null;
  enabled: boolean;
  schedule_mode: "daily" | "weekly" | "manual";
  breadth: ResearchBreadth;
  lens_count: number;
  enabled_lens_ids: string[];
  paused_until: string | null;
  last_successful_scheduled_run_at: string | null;
  inbox: ResearchInboxUsage;
  manual_queue: { pending: number; claimed: number };
  latest_run: ResearchRunSummary | null;
}
export interface ResearchProfileDetail {
  profile: ResearchProfile;
  canonical_content: string;
  runtime_state: { profile_id: string; paused_until: string | null; last_successful_scheduled_run_at: string | null; created_at: string; updated_at: string } | null;
  inbox: ResearchInboxUsage;
  latest_run: ResearchRunSummary | null;
  resume_options: Array<"catch_up" | "from_now">;
}
export interface ResearchWork {
  id: string;
  canonical_key: string;
  title: string;
  normalized_title: string;
  abstract: string | null;
  authors: string[];
  year: number | null;
  published_at: string | null;
  venue: string | null;
  doi: string | null;
  arxiv_id: string | null;
  openalex_id: string | null;
  semantic_scholar_id: string | null;
  url: string | null;
  created_at: string;
  updated_at: string;
}
export interface ResearchRelation { entity_type: "document" | "term" | "source" | "collection"; entity_id: string; relation: "extends" | "alternative" | "contrasts" | "applies" | "reviews" | "related"; reason: string }
export interface ResearchAnalysis {
  relevant: boolean;
  profile_relevance: number;
  knowledge_relevance: number;
  novelty_to_library: number;
  matched_lenses: string[];
  matched_topics: string[];
  summary: string;
  why_relevant: string;
  reading_reason: string;
  existing_relations: ResearchRelation[];
  suggested_collection?: string | null;
  suggested_section?: string | null;
}
export interface ResearchCandidate {
  id: string;
  work_id: string;
  profile_id: string;
  status: ResearchCandidateStatus;
  primary_lens_id: string | null;
  analysis_id: string;
  user_note: string | null;
  dismiss_reason: ResearchDismissReason | null;
  created_at: string;
  updated_at: string;
  first_viewed_at: string | null;
  last_viewed_at: string | null;
  decided_at: string | null;
}
export interface ResearchCandidateListItem {
  candidate: ResearchCandidate;
  work: ResearchWork;
  analysis: ResearchAnalysis;
  recommended_score: number;
}
export interface ResearchDiscovery {
  id: string;
  work_id: string;
  profile_id: string;
  lens_id: string;
  provider: "arxiv" | "openalex" | "crossref";
  provider_record_id: string;
  query_key: string;
  query_text: string;
  metadata: Record<string, unknown>;
  discovered_at: string;
}
export interface ResearchAnalysisInputContext {
  analysis_version?: number;
  prompt_version?: string;
  provider?: string;
  model?: string;
  work?: Partial<Omit<ResearchWork, "created_at" | "updated_at">>;
  profile?: {
    id?: string;
    title?: string;
    description?: string | null;
    breadth?: ResearchBreadth;
    breadth_policy?: string;
  };
  matched_lens?: Partial<ResearchLens>;
  knowledge_context?: {
    focus_query?: string;
    cards?: Array<{
      entity_type: string;
      entity_id: string;
      title: string;
      review_status: string;
      topics: string[];
      domains: string[];
      relevant_sections: Array<{ heading: string; excerpt: string }>;
      metadata: Record<string, unknown>;
      pinned: boolean;
      retrieval_score: number;
    }>;
    budget?: number;
    omitted_count?: number;
  };
}
export interface ResearchWorkAnalysis {
  id: string;
  work_id: string;
  profile_id: string;
  input_hash: string;
  outcome: "surface" | "filtered";
  analysis: ResearchAnalysis;
  provider: string;
  model: string;
  prompt_version: string;
  analysis_version: number;
  context_entity_ids: string[];
  input_context: ResearchAnalysisInputContext;
  analyzed_at: string;
}
export interface ResearchCandidateDetail {
  candidate: ResearchCandidate;
  work: ResearchWork;
  analysis: ResearchWorkAnalysis;
  conversion_blocker: "ambiguous_source" | null;
  source_match_candidates: Array<{ id: string; title: string; matched_by: string[] }>;
  discoveries: ResearchDiscovery[];
  knowledge_relations: ResearchRelation[];
  linked_entities: Array<{ entity_type: "source" | "document"; entity_id: string; relation_type: "source" | "note"; created_at: string }>;
  pending_links: Array<{ id: string; group_id: string; draft_id: string; intended_entity_type: string; intended_entity_id: string; relation_type: string; created_at: string }>;
}
export interface ResearchRun extends ResearchRunSummary {
  profile_id: string;
  request_id: string | null;
  profile_content_hash: string;
  effective_config: Record<string, unknown>;
  new_work_count: number;
  duplicate_count: number;
  deterministic_filtered_count: number;
  analysis_attempt_count: number;
  analyzed_count: number;
  analysis_counts_known: boolean;
  provider_summary: Record<string, { requests: number; pages: number; works: number; errors: number; circuit_open: boolean }>;
  error_summary: string | null;
}
export interface ResearchCandidateList {
  candidates: ResearchCandidateListItem[];
  count: number;
  offset: number;
  limit: number;
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
    let body: { detail?: string; code?: string; expected_revision?: number; current_revision?: number } = {};
    try {
      body = (await response.json()) as typeof body;
      if (body.detail) message = body.detail;
    } catch {
      // Keep the HTTP status when the server does not return JSON.
    }
    throw Object.assign(new Error(message), {
      status: response.status,
      code: body.code,
      expected_revision: body.expected_revision,
      current_revision: body.current_revision,
    }) satisfies ApiError;
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
  return request<DraftAcquireResult>("/api/drafts", {
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

export function getDraft(draftId: string) {
  return request<Draft>(`/api/drafts/${encodeURIComponent(draftId)}`);
}

export function compareDraft(draftId: string) {
  return request<DraftComparison>(`/api/drafts/${encodeURIComponent(draftId)}/compare`);
}

export function preflightDraft(draftId: string) {
  return request<DraftPreflight>(`/api/drafts/${encodeURIComponent(draftId)}/preflight`);
}

export function preflightDraftsBatch(drafts: DraftPublishExpectation[]) {
  return request<BatchDraftPreflight>("/api/publish/preflight-batch", {
    method: "POST",
    body: JSON.stringify({ drafts }),
  });
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

export function publishDraft(
  draftId: string,
  expectedRevision: number,
) {
  return request<PublishedDraft>("/api/publish", {
    method: "POST",
    body: JSON.stringify({
      draft_id: draftId,
      expected_revision: expectedRevision,
    }),
  });
}

export function publishDraftsBatch(drafts: DraftPublishExpectation[], commitMessage?: string) {
  return request<BatchPublishedDrafts>("/api/publish/batch", {
    method: "POST",
    body: JSON.stringify({ drafts, commit_message: commitMessage }),
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

export function rejectProposal(proposalId: string) {
  return request<Proposal>(`/api/proposals/${encodeURIComponent(proposalId)}/reject`, {
    method: "POST",
    body: JSON.stringify({ review_note: "用户拒绝此 Proposal" }),
  });
}

export function applyProposalToDraft(
  proposalId: string,
  draftId: string,
  expectedDraftRevision: number,
) {
  return request<ProposalApplyResult>(`/api/proposals/${encodeURIComponent(proposalId)}/apply`, {
    method: "POST",
    body: JSON.stringify({
      draft_id: draftId,
      expected_draft_revision: expectedDraftRevision,
    }),
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

export function listResearchProfiles() {
  return request<ResearchProfileSummary[]>("/api/research/profiles");
}

export function getResearchProfile(profileId: string) {
  return request<ResearchProfileDetail>(`/api/research/profiles/${encodeURIComponent(profileId)}`);
}

export function pauseResearchProfile(profileId: string, body: { days?: number; until?: string }) {
  return request<{ runtime_state: NonNullable<ResearchProfileDetail["runtime_state"]> }>(
    `/api/research/profiles/${encodeURIComponent(profileId)}/pause`,
    { method: "POST", body: JSON.stringify(body) },
  );
}

export function resumeResearchProfile(profileId: string, body: { strategy: "catch_up" | "from_now"; catchup_days?: number }) {
  return request<{ runtime_state: NonNullable<ResearchProfileDetail["runtime_state"]>; strategy: "catch_up" | "from_now"; watermark_skipped: boolean }>(
    `/api/research/profiles/${encodeURIComponent(profileId)}/resume`,
    { method: "POST", body: JSON.stringify(body) },
  );
}

export interface QueueResearchRunInput {
  lenses: string[];
  breadth?: ResearchBreadth;
  date_range?: { mode: "incremental" | "last_7_days" | "last_30_days" | "last_90_days" | "custom"; start?: string; end?: string };
  additional_queries?: string[];
  additional_query_lens?: string;
}

export function queueResearchRun(profileId: string, body: QueueResearchRunInput) {
  return request<{ request_id: string; status: "pending" | "claimed" | "completed" | "failed" }>(
    `/api/research/profiles/${encodeURIComponent(profileId)}/runs`,
    { method: "POST", body: JSON.stringify(body) },
  );
}

export function listResearchCandidates(filters: {
  profile_id?: string; status?: ResearchCandidateStatus; lens?: string; sort?: ResearchSort; offset?: number; limit?: number;
}) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) if (value !== undefined && value !== "") params.set(key, String(value));
  return request<ResearchCandidateList>(`/api/research/candidates?${params.toString()}`);
}

export function getResearchCandidate(candidateId: string) {
  return request<ResearchCandidateDetail>(`/api/research/candidates/${encodeURIComponent(candidateId)}`);
}

export function shortlistResearchCandidate(candidateId: string, note?: string) {
  return request<ResearchCandidate>(`/api/research/candidates/${encodeURIComponent(candidateId)}/shortlist`, {
    method: "POST", body: JSON.stringify(note ? { note } : {}),
  });
}

export function updateResearchCandidateNote(candidateId: string, note: string) {
  return request<ResearchCandidate>(`/api/research/candidates/${encodeURIComponent(candidateId)}/note`, {
    method: "PATCH", body: JSON.stringify({ note }),
  });
}

export function dismissResearchCandidate(candidateId: string, reason?: ResearchDismissReason, note?: string) {
  return request<ResearchCandidate>(`/api/research/candidates/${encodeURIComponent(candidateId)}/dismiss`, {
    method: "POST", body: JSON.stringify({ ...(reason ? { reason } : {}), ...(note ? { note } : {}) }),
  });
}

export function saveResearchSource(candidateId: string) {
  return request<{
    action: "linked_existing" | "draft_created" | "draft_reused";
    source_id: string;
    draft_id: string | null;
    candidate: ResearchCandidate;
  }>(`/api/research/candidates/${encodeURIComponent(candidateId)}/save-source`, { method: "POST" });
}

export interface CreateResearchNoteInput {
  document_type: "paper-note" | "learning-note";
  template: "structured" | "blank";
  collection_id?: string;
  section_id?: string;
}

export interface CreateResearchNoteResult {
  group_id: string;
  source_draft_id: string | null;
  document_draft_id: string;
  collection_draft_id: string | null;
  collection_id: string | null;
  document_id: string;
  source_id: string | null;
}

export function createResearchNote(candidateId: string, body: CreateResearchNoteInput) {
  return request<CreateResearchNoteResult>(
    `/api/research/candidates/${encodeURIComponent(candidateId)}/create-note`,
    { method: "POST", body: JSON.stringify(body) },
  );
}

export function listResearchRuns(profileId?: string, offset = 0, limit = 50) {
  const params = new URLSearchParams({ offset: String(offset), limit: String(limit) });
  if (profileId) params.set("profile_id", profileId);
  return request<{ runs: ResearchRun[]; count: number }>(`/api/research/runs?${params.toString()}`);
}

export function getResearchRun(runId: string) {
  return request<ResearchRun>(`/api/research/runs/${encodeURIComponent(runId)}`);
}

function typePath(type: EntityType) {
  return type === "document" ? "documents" : `${type}s`;
}
