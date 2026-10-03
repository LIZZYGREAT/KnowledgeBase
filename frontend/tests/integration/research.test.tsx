import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "../../src/App";

vi.mock("../../src/Workspace", async () => {
  const React = await import("react");
  return { WorkspacePage: () => React.createElement("div", null, "Source Workspace") };
});

const runRequestId = "research-request-123";

describe("Research workspace", () => {
  let mockFetch: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    window.history.replaceState({}, "", "/research");
    vi.spyOn(window, "scrollTo").mockImplementation(() => undefined);
    mockFetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/api/collections?status=active") return jsonResponse([{ id: "continual-learning", title: "Continual Learning", description: null, status: "active", position: 0, node_count: 1, entity_count: 0, document_count: 0 }]);
      if (path === "/api/collections/continual-learning") return jsonResponse({ id: "continual-learning", title: "Continual Learning", description: null, status: "active", position: 0, nodes: [{ id: "regularization", kind: "section", title: "Regularization", children: [] }] });
      if (path === "/api/drafts?entity_type=collection&entity_id=continual-learning") return jsonResponse([]);
      if (path === "/api/research/profiles") return jsonResponse([profileSummary]);
      if (path === "/api/research/profiles/continual-learning") return jsonResponse(profileDetail);
      if (path.startsWith("/api/research/candidates?") && path.includes("status=new")) return jsonResponse({ candidates: [candidateListItem], count: 1, offset: 0, limit: 50 });
      if (path === "/api/research/candidates/candidate-1") return jsonResponse(candidateDetail);
      if (path === "/api/research/runs?offset=0&limit=50&profile_id=continual-learning") return jsonResponse({ runs: [], count: 0 });
      if (path === "/api/research/profiles/continual-learning/runs" && init?.method === "POST") return jsonResponse({ request_id: runRequestId, status: "pending" }, 202);
      if (path === "/api/research/candidates/candidate-1/shortlist" && init?.method === "POST") return jsonResponse({ ...candidate, status: "shortlisted" });
      if (path === "/api/research/candidates/candidate-1/save-source" && init?.method === "POST") return jsonResponse({ action: "draft_created", source_id: "research-paper", draft_id: "source-draft-1", candidate });
      if (path === "/api/research/candidates/candidate-1/create-note" && init?.method === "POST") return jsonResponse({ group_id: "group-1", source_draft_id: "source-draft-1", document_draft_id: "document-draft-1", collection_draft_id: "collection-draft-1", collection_id: "continual-learning", document_id: "research-note-1", source_id: "research-paper" });
      return jsonResponse({ detail: `Unexpected request: ${path}` }, 404);
    });
    vi.stubGlobal("fetch", mockFetch);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("shows the Research inbox and explains candidate provenance", async () => {
    render(<App />);

    expect(screen.getByRole("button", { name: /Research/ }).getAttribute("aria-current")).toBe("page");
    expect(await screen.findByText("Discoveries", {}, { timeout: 5000 })).toBeTruthy();
    expect(await screen.findByRole("heading", { name: "A New Regularization Method" }, { timeout: 5000 })).toBeTruthy();
    expect(screen.getByText("Related knowledge")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: /Why this candidate/ }));
    expect(await screen.findByRole("heading", { name: "Why this candidate" })).toBeTruthy();
    expect(screen.getByText("Matched query")).toBeTruthy();
    expect(screen.getByText("research-candidate-analysis-v1")).toBeTruthy();
    expect(screen.getByText("fisher information catastrophic forgetting")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    fireEvent.click(screen.getByRole("button", { name: "Shortlist" }));
    await waitFor(() => expect(mockFetch.mock.calls.some(([input, init]) => String(input) === "/api/research/candidates/candidate-1/shortlist" && init?.method === "POST")).toBe(true));
  });

  it("queues a manual run without executing it in the page request", async () => {
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Search Now" }));
    fireEvent.change(screen.getByLabelText(/额外检索词/), { target: { value: "dynamic fisher continual learning" } });
    fireEvent.click(screen.getByRole("button", { name: "加入搜索队列" }));

    expect(await screen.findByText(/Search queued/)).toBeTruthy();
    const call = mockFetch.mock.calls.find(([input, init]) => String(input) === "/api/research/profiles/continual-learning/runs" && init?.method === "POST");
    expect(call).toBeTruthy();
    const body = JSON.parse(String(call?.[1]?.body));
    expect(body).toMatchObject({ lenses: ["regularization"], breadth: "balanced", additional_queries: ["dynamic fisher continual learning"] });
    expect(mockFetch.mock.calls.some(([input]) => String(input).includes("/api/research/runs/") && !String(input).includes("offset="))).toBe(false);
  });

  it("opens the Source Draft in the Unified Workspace", async () => {
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Save Source" }));

    expect(await screen.findByText("Source Workspace")).toBeTruthy();
    expect(window.location.pathname).toBe("/sources/research-paper");
    expect(window.location.search).toBe("?edit=1");
  });

  it("creates a structured note group and enters batch Workspace review", async () => {
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Create Note" }));
    expect(await screen.findByRole("heading", { name: "Create Research Note" })).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Collection"), { target: { value: "continual-learning" } });
    await screen.findByRole("option", { name: "Regularization" });
    fireEvent.change(screen.getByLabelText("Section"), { target: { value: "regularization" } });
    fireEvent.click(screen.getByRole("button", { name: "Create" }));

    expect(await screen.findByText("Source Workspace")).toBeTruthy();
    expect(window.location.pathname).toBe("/documents/research-note-1");
    expect(window.location.search).toBe("?collection=continual-learning&edit=1&publishAll=1&relatedDraft=source-draft-1&researchGroup=group-1");
    const call = mockFetch.mock.calls.find(([input, init]) => String(input) === "/api/research/candidates/candidate-1/create-note" && init?.method === "POST");
    expect(JSON.parse(String(call?.[1]?.body))).toEqual({ document_type: "paper-note", template: "structured", collection_id: "continual-learning", section_id: "regularization" });
  });
});

function jsonResponse(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json" } });
}

const profile = {
  schema_version: 1,
  id: "continual-learning",
  title: "Continual Learning",
  description: "Continual learning research.",
  enabled: true,
  lenses: [{ id: "regularization", title: "Regularization", enabled: true, priority: "high", queries: ["fisher information catastrophic forgetting"], include_terms: ["fisher information"], exclude_terms: [] }],
  exclude_terms: [],
  providers: { discovery: ["arxiv"], enrichment: [] },
  context: { collections: [], documents: [], dynamic_retrieval: { enabled: true, scope: "entire-library" } },
  schedule: { mode: "daily" },
  search: { breadth: "balanced", initial_lookback_days: 30, max_catchup_days: 30, max_candidates_per_run: 10 },
  inbox: { max_new_candidates: 20 },
  ai_analysis: { enabled: true, provider: "deepseek" },
};

const profileSummary = {
  id: profile.id,
  title: profile.title,
  description: profile.description,
  enabled: true,
  schedule_mode: "daily",
  breadth: "balanced",
  lens_count: 1,
  enabled_lens_ids: ["regularization"],
  paused_until: null,
  last_successful_scheduled_run_at: null,
  inbox: { new_count: 1, capacity: 20, remaining: 19 },
  latest_run: null,
};

const profileDetail = {
  profile,
  runtime_state: { profile_id: profile.id, paused_until: null, last_successful_scheduled_run_at: null, created_at: "2026-10-01T00:00:00+00:00", updated_at: "2026-10-01T00:00:00+00:00" },
  inbox: profileSummary.inbox,
  latest_run: null,
  resume_options: ["catch_up", "from_now"],
};

const candidate = {
  id: "candidate-1",
  work_id: "work-1",
  profile_id: profile.id,
  status: "new",
  primary_lens_id: "regularization",
  analysis_id: "analysis-1",
  user_note: null,
  dismiss_reason: null,
  created_at: "2026-10-01T00:00:00+00:00",
  updated_at: "2026-10-01T00:00:00+00:00",
  first_viewed_at: null,
  last_viewed_at: null,
  decided_at: null,
};

const work = {
  id: "work-1", canonical_key: "arxiv:2501.00001", title: "A New Regularization Method", normalized_title: "a new regularization method", abstract: "A useful method for reducing catastrophic forgetting.",
  authors: ["Zhang, L."], year: 2026, published_at: "2026-01-01", venue: "arXiv", doi: null, arxiv_id: "2501.00001", openalex_id: null, semantic_scholar_id: null, url: "https://arxiv.org/abs/2501.00001", created_at: candidate.created_at, updated_at: candidate.updated_at,
};

const analysis = {
  relevant: true, profile_relevance: 0.91, knowledge_relevance: 0.8, novelty_to_library: 0.73, matched_lenses: ["regularization"], matched_topics: ["Fisher information", "Catastrophic forgetting"],
  summary: "A new importance estimation method for continual learning.", why_relevant: "It matches the regularization Lens and studies parameter importance.", reading_reason: "Compare its adaptive estimates against EWC.", existing_relations: [{ entity_type: "term", entity_id: "fisher-information", relation: "extends", reason: "Uses Fisher information to estimate parameter importance." }],
};

const candidateListItem = { candidate, work, analysis, recommended_score: 0.84 };
const candidateDetail = {
  candidate: { ...candidate, first_viewed_at: "2026-10-03T00:00:00+00:00", last_viewed_at: "2026-10-03T00:00:00+00:00" },
  work,
  analysis: { id: "analysis-1", work_id: work.id, profile_id: profile.id, input_hash: "sha256:abc", outcome: "surface", analysis, provider: "deepseek", model: "deepseek-chat", prompt_version: "research-candidate-analysis-v1", analysis_version: 1, context_entity_ids: ["gem-sgd"], analyzed_at: "2026-10-03T00:00:00+00:00" },
  discoveries: [{ id: "discovery-1", work_id: work.id, profile_id: profile.id, lens_id: "regularization", provider: "arxiv", provider_record_id: "2501.00001", query_key: "query-key", query_text: "fisher information catastrophic forgetting", metadata: {}, discovered_at: "2026-10-03T00:00:00+00:00" }],
  knowledge_relations: analysis.existing_relations,
  linked_entities: [],
  pending_links: [],
};
