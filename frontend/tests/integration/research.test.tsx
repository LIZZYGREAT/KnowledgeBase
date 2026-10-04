import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { parse, stringify } from "yaml";
import App from "../../src/App";
import { ResearchProfilePanel } from "../../src/ResearchProfile";
import { ResearchProfileDefaultsEditor } from "../../src/ResearchProfileDefaultsEditor";
import { ResearchProfileCreateDialog } from "../../src/ResearchProfileCreateDialog";
import { ResearchCandidateCard, ResearchCreateNoteDialog } from "../../src/ResearchCandidate";
import { ResearchRunDrawer, ResearchRunList } from "../../src/ResearchRun";
import type { ResearchCandidateListItem, ResearchProfile, ResearchRun, ResearchRunStatus } from "../../src/api";

vi.mock("../../src/Workspace", async () => {
  const React = await import("react");
  return { WorkspacePage: () => React.createElement("div", null, "Source Workspace") };
});

const runRequestId = "research-request-123";

describe("Research workspace", () => {
  let mockFetch: ReturnType<typeof vi.fn>;
  let responseProfileDetail = profileDetail;
  let responseProfileSummary = profileSummary;
  let responseCandidateDetail = candidateDetail;
  let responseCollection = { id: "continual-learning", title: "Continual Learning", description: null, status: "active", position: 0, nodes: [{ id: "regularization", kind: "section", title: "Regularization", children: [] }] };
  let responseDocuments: Array<{ id: string; title: string }> = [];
  let researchProfileDraft: Record<string, unknown> | null = null;
  let createDraftCreatedInThisFlow = true;
  let reactivationReviewResponse = { required: false, triggers: [], streams: [], max_catchup_days: 30, strategies: [] };

  beforeEach(() => {
    responseProfileDetail = profileDetail;
    responseProfileSummary = profileSummary;
    responseCandidateDetail = candidateDetail;
    responseCollection = { id: "continual-learning", title: "Continual Learning", description: null, status: "active", position: 0, nodes: [{ id: "regularization", kind: "section", title: "Regularization", children: [] }] };
    responseDocuments = [];
    researchProfileDraft = null;
    createDraftCreatedInThisFlow = true;
    reactivationReviewResponse = { required: false, triggers: [], streams: [], max_catchup_days: 30, strategies: [] };
    window.history.replaceState({}, "", "/research");
    vi.spyOn(window, "scrollTo").mockImplementation(() => undefined);
    mockFetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/api/collections?status=active") return jsonResponse([{ id: "continual-learning", title: "Continual Learning", description: null, status: "active", position: 0, node_count: 1, entity_count: 0, document_count: 0 }]);
      if (path === "/api/collections/continual-learning") return jsonResponse(responseCollection);
      if (path === "/api/drafts?entity_type=collection&entity_id=continual-learning") return jsonResponse([]);
      if (path === "/api/documents?limit=100&offset=0") return jsonResponse(responseDocuments);
      if (path === "/api/research/profiles") return jsonResponse([responseProfileSummary]);
      if (path === "/api/research/profiles/continual-learning") return jsonResponse(responseProfileDetail);
      if (path.startsWith("/api/drafts?entity_type=research_profile&entity_id=")) {
        const entityId = new URLSearchParams(path.split("?")[1]).get("entity_id");
        return jsonResponse(researchProfileDraft?.entity_id === entityId ? [researchProfileDraft] : []);
      }
      if (path === "/api/drafts" && init?.method === "POST") {
        const body = JSON.parse(String(init.body));
        researchProfileDraft = { id: "profile-draft-1", entity_type: "research_profile", entity_id: body.entity_id, base_git_revision: "abc123", base_content_hash: "a".repeat(64), content: body.content, revision: 1, created_at: "2026-10-03T00:00:00+00:00", updated_at: "2026-10-03T00:00:00+00:00" };
        return jsonResponse({ draft: researchProfileDraft, created: createDraftCreatedInThisFlow }, 201);
      }
      if (path === "/api/drafts/profile-draft-1" && init?.method === "DELETE") return new Response(null, { status: 204 });
      if (path === "/api/drafts/profile-draft-1/compare" && researchProfileDraft) {
        const canonical = JSON.stringify(profile, null, 2);
        return jsonResponse({ draft: researchProfileDraft, base_content: canonical, current_content: canonical, current_git_revision: "abc123", current_content_hash: "a".repeat(64), canonical_changed: false });
      }
      if (path === "/api/drafts/profile-draft-1/preflight") return jsonResponse({ draft_id: "profile-draft-1", valid: true, conflict: false, errors: [], warnings: [] });
      if (path === "/api/research/profiles/continual-learning/reactivation-review" && init?.method === "POST") return jsonResponse(reactivationReviewResponse);
      if (path === "/api/publish" && init?.method === "POST") return jsonResponse({ draft_id: "profile-draft-1", entity_type: "research_profile", entity_id: "continual-learning", commit_revision: "def456", warnings: [] });
      if (path.startsWith("/api/research/candidates?") && path.includes("status=new")) return jsonResponse({ candidates: [candidateListItem], count: 1, offset: 0, limit: 50 });
      if (path === "/api/research/candidates/candidate-1") return jsonResponse(responseCandidateDetail);
      if (path === "/api/research/runs?offset=0&limit=50&profile_id=continual-learning") return jsonResponse({ runs: [], count: 0 });
      if (path === "/api/research/profiles/continual-learning/runs" && init?.method === "POST") {
        responseProfileSummary = {
          ...responseProfileSummary,
          manual_queue: { ...responseProfileSummary.manual_queue, pending: responseProfileSummary.manual_queue.pending + 1 },
        };
        return jsonResponse({ request_id: runRequestId, status: "pending" }, 202);
      }
      if (path === "/api/research/candidates/candidate-1/shortlist" && init?.method === "POST") return jsonResponse({ ...candidate, status: "shortlisted" });
      if (path === "/api/research/candidates/candidate-1/note" && init?.method === "PATCH") return jsonResponse({ ...candidate, ...JSON.parse(String(init.body)), status: "shortlisted" });
      if (path === "/api/research/candidates/candidate-1/save-source" && init?.method === "POST") return jsonResponse({ action: "draft_created", source_id: "research-paper", draft_id: "source-draft-1", candidate });
      if (path === "/api/research/candidates/candidate-1/create-note" && init?.method === "POST") return jsonResponse({ group_id: "group-1", source_draft_id: "source-draft-1", document_draft_id: "document-draft-1", collection_draft_id: "collection-draft-1", collection_id: "continual-learning", document_id: "research-note-1", source_id: "research-paper" });
      return jsonResponse({ detail: `Unexpected request: ${path}` }, 404);
    });
    vi.stubGlobal("fetch", mockFetch);
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("shows the Research inbox and explains candidate provenance", async () => {
    responseCandidateDetail = {
      ...candidateDetail,
      candidate: { ...candidateDetail.candidate, status: "shortlisted", user_note: "Read after the current batch." },
      conversion_blocker: "ambiguous_source",
    };
    render(<App />);

    expect(screen.getByRole("button", { name: /Research/ }).getAttribute("aria-current")).toBe("page");
    expect(await screen.findByText("Discoveries", {}, { timeout: 5000 })).toBeTruthy();
    expect(await screen.findByRole("heading", { name: "A New Regularization Method" }, { timeout: 5000 })).toBeTruthy();
    expect(screen.getByText("Related knowledge")).toBeTruthy();
    expect(screen.getByText("Why read it")).toBeTruthy();
    expect(screen.queryByText("What may be new")).toBeNull();
    expect(screen.getByText("Relevance: High")).toBeTruthy();
    expect(screen.getByText("Library novelty: Medium")).toBeTruthy();
    expect(screen.getByText(/排序信号/)).toBeTruthy();
    expect(screen.queryByText("73% library novelty")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: /Why this candidate/ }));
    expect(await screen.findByRole("heading", { name: "Why this candidate" })).toBeTruthy();
    expect(screen.getByRole("alert").textContent).toContain("Canonical Source metadata is ambiguous");
    expect(screen.getByText(/模型语义信号（0–1）/)).toBeTruthy();
    expect(screen.getByText("0.91")).toBeTruthy();
    expect(screen.getByText("Matched query")).toBeTruthy();
    expect(screen.getByText("research-candidate-analysis-v1")).toBeTruthy();
    expect(screen.getAllByText("fisher information catastrophic forgetting").length).toBeGreaterThan(1);
    expect(screen.getByRole("heading", { name: "Analysis-time context" })).toBeTruthy();
    expect(screen.getByText("Snapshot excerpt used at analysis time.")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Current knowledge links" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Suggested destination" })).toBeTruthy();
    expect(screen.getByText("Collection ID")).toBeTruthy();
    expect(screen.getByText("Source · published-paper")).toBeTruthy();
    fireEvent.click(await screen.findByRole("button", { name: "Edit note" }));
    fireEvent.change(await screen.findByRole("textbox", { name: "Candidate note" }), { target: { value: "Compare with replay-based methods." } });
    fireEvent.click(screen.getByRole("button", { name: "Save note" }));
    await waitFor(() => expect(mockFetch.mock.calls.some(([input, init]) => String(input) === "/api/research/candidates/candidate-1/note" && init?.method === "PATCH")).toBe(true));
    const noteCall = mockFetch.mock.calls.find(([input, init]) => String(input) === "/api/research/candidates/candidate-1/note" && init?.method === "PATCH");
    expect(JSON.parse(String(noteCall?.[1]?.body))).toEqual({ note: "Compare with replay-based methods." });
    expect(await screen.findByText("Compare with replay-based methods.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    fireEvent.click(await screen.findByRole("button", { name: "Shortlist" }));
    expect(await screen.findByRole("heading", { name: "Shortlist candidate" })).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Shortlist note"), { target: { value: "Compare with the replay method." } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm Shortlist" }));
    await waitFor(() => expect(mockFetch.mock.calls.some(([input, init]) => String(input) === "/api/research/candidates/candidate-1/shortlist" && init?.method === "POST")).toBe(true));
    const shortlistCall = mockFetch.mock.calls.find(([input, init]) => String(input) === "/api/research/candidates/candidate-1/shortlist" && init?.method === "POST");
    expect(JSON.parse(String(shortlistCall?.[1]?.body))).toEqual({ note: "Compare with the replay method." });
  }, 10_000);

  it("queues a manual run without executing it in the page request", async () => {
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Search Now" }));
    fireEvent.change(screen.getByLabelText(/额外检索词/), { target: { value: "dynamic fisher continual learning" } });
    fireEvent.click(screen.getByRole("button", { name: "加入搜索队列" }));

    expect(await screen.findByText(/Search queued/)).toBeTruthy();
    expect(await screen.findByText("1 manual search queued")).toBeTruthy();
    const call = mockFetch.mock.calls.find(([input, init]) => String(input) === "/api/research/profiles/continual-learning/runs" && init?.method === "POST");
    expect(call).toBeTruthy();
    const body = JSON.parse(String(call?.[1]?.body));
    expect(body).toMatchObject({ lenses: ["regularization"], breadth: "balanced", additional_queries: ["dynamic fisher continual learning"], additional_query_lens: "regularization" });
    expect(mockFetch.mock.calls.some(([input]) => String(input).includes("/api/research/runs/") && !String(input).includes("offset="))).toBe(false);
  });

  it("shows pending and claimed manual requests from the persisted Profile summary", async () => {
    responseProfileSummary = {
      ...profileSummary,
      manual_queue: { pending: 2, claimed: 1 },
    };
    render(<App />);

    const status = await screen.findByText((_, element) =>
      element?.classList.contains("research-search-block-note")
      && element.textContent?.includes("2 manual searches queued") === true,
    );
    expect(status.textContent).toContain("1 Research request running");
  });

  it("shows the Lens configuration captured by the Run, including per-run overrides", async () => {
    const snapshot = {
      ...profile,
      lenses: [
        { id: "lens-a", title: "Lens A", enabled: true },
        { id: "lens-b", title: "Lens B", enabled: true },
        { id: "lens-c", title: "Lens C", enabled: true },
      ],
    };
    const run = {
      id: "run-lens-override",
      trigger: "manual",
      status: "success",
      started_at: "2026-10-04T00:00:00+00:00",
      finished_at: "2026-10-04T00:01:00+00:00",
      fetched_count: 3,
      surfaced_count: 2,
      profile_id: profile.id,
      request_id: null,
      profile_content_hash: "sha256:abc",
      effective_config: { profile: snapshot, lens_overrides: { "lens-a": false, "lens-b": true, "lens-c": false }, additional_queries: [], manual_incremental: false },
      new_work_count: 3,
      duplicate_count: 0,
      deterministic_filtered_count: 0,
      analysis_attempt_count: 3,
      analyzed_count: 2,
      analysis_counts_known: true,
      provider_summary: {},
      error_summary: null,
    } satisfies ResearchRun;
    render(<ResearchRunDrawer run={run} onClose={() => undefined} />);

    const inspector = screen.getByRole("dialog", { name: "Research Run" });
    expect(within(inspector).getByText("Lens B")).toBeTruthy();
    expect(within(inspector).queryByText("Lens A")).toBeNull();
    expect(within(inspector).queryByText("Lens C")).toBeNull();
  });

  it("renders normal Run flow-control states without failure tones", () => {
    const statuses: Array<[ResearchRunStatus, string, string]> = [
      ["success", "green", "✓"],
      ["running", "blue", "◷"],
      ["partial", "amber", "·"],
      ["skipped_paused", "amber", "·"],
      ["skipped_disabled", "amber", "·"],
      ["skipped_ai_disabled", "amber", "·"],
      ["skipped_inbox_full", "amber", "·"],
      ["capacity_reached", "amber", "·"],
      ["failed", "rose", "!"],
      ["interrupted", "rose", "!"],
    ];
    const runs = statuses.map(([status], index) => ({
      id: `run-${index}`,
      trigger: "scheduled",
      status,
      started_at: "2026-10-04T00:00:00+00:00",
      finished_at: null,
      fetched_count: 0,
      surfaced_count: 0,
      profile_id: profile.id,
      request_id: null,
      profile_content_hash: "sha256:abc",
      effective_config: {},
      new_work_count: 0,
      duplicate_count: 0,
      deterministic_filtered_count: 0,
      analysis_attempt_count: 0,
      analyzed_count: 0,
      analysis_counts_known: true,
      provider_summary: {},
      error_summary: null,
    } satisfies ResearchRun));
    render(<ResearchRunList runs={runs} count={runs.length} loading={false} onOpen={() => undefined} />);

    for (const [status, tone, mark] of statuses) {
      const label = status.replaceAll("_", " ");
      const chip = screen.getByText(label, { selector: ".chip" });
      expect(chip.classList.contains(`chip-${tone}`)).toBe(true);
      const row = chip.closest(".research-run-row");
      expect(row?.querySelector(".research-run-mark")?.textContent).toBe(mark);
    }
  });

  it("labels the candidate reading reason as why to read it", () => {
    render(<ResearchCandidateCard
      item={candidateListItem as ResearchCandidateListItem}
      profile={profile as ResearchProfile}
      selected={false}
      selectable={false}
      busy={false}
      onSelect={() => undefined}
      onDetails={() => undefined}
      onShortlist={() => undefined}
      onDismiss={() => undefined}
      onSaveSource={() => undefined}
      onCreateNote={() => undefined}
    />);

    expect(screen.getByText("Why read it")).toBeTruthy();
    expect(screen.getByText("Compare its adaptive estimates against EWC.")).toBeTruthy();
  });

  it("creates a new Profile Draft from the simple setup fields", async () => {
    const created = vi.fn();
    render(<ResearchProfileCreateDialog profiles={[profileSummary]} sourceProfile={null} onClose={() => undefined} onCreated={created} />);
    fireEvent.change(screen.getByLabelText("New Profile ID"), { target: { value: "3dgs" } });
    fireEvent.change(screen.getByLabelText("New Profile title"), { target: { value: "3D Gaussian Splatting" } });
    fireEvent.change(screen.getByLabelText("New Profile description"), { target: { value: "New view synthesis work." } });
    fireEvent.change(screen.getByLabelText("Initial Lens ID"), { target: { value: "rendering-quality" } });
    fireEvent.change(screen.getByLabelText("Initial Lens title"), { target: { value: "Rendering Quality" } });
    fireEvent.change(screen.getByLabelText("Initial Query"), { target: { value: "continual learning regularization" } });
    expect(screen.queryByLabelText("New Profile schedule")).toBeNull();
    expect(screen.queryByLabelText("New Profile breadth")).toBeNull();
    expect(screen.queryByLabelText("New Profile inbox cap")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Create Draft" }));

    await waitFor(() => expect(created).toHaveBeenCalledTimes(1));
    const call = mockFetch.mock.calls.find(([input, init]) => String(input) === "/api/drafts" && init?.method === "POST");
    const body = JSON.parse(String(call?.[1]?.body));
    const draftProfile = parse(body.content);
    expect(body).toMatchObject({ entity_type: "research_profile", entity_id: "3dgs" });
    expect(draftProfile).toMatchObject({
      id: "3dgs",
      title: "3D Gaussian Splatting",
      description: "New view synthesis work.",
      lenses: [{ id: "rendering-quality", title: "Rendering Quality", queries: ["continual learning regularization"] }],
      schedule: { mode: "daily" },
      search: { breadth: "balanced" },
      inbox: { max_new_candidates: 20 },
      providers: { discovery: ["arxiv"], enrichment: [] },
      ai_analysis: { enabled: false, provider: "deepseek" },
    });
  });

  it("resumes an existing Profile Draft without deleting it when the editor closes", async () => {
    createDraftCreatedInThisFlow = false;
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "New Profile" }));
    fireEvent.change(screen.getByLabelText("New Profile ID"), { target: { value: "resumed-profile" } });
    fireEvent.change(screen.getByLabelText("New Profile title"), { target: { value: "Resumed Profile" } });
    fireEvent.change(screen.getByLabelText("Initial Query"), { target: { value: "continual learning" } });
    fireEvent.click(screen.getByRole("button", { name: "Create Draft" }));

    expect(await screen.findByText("Existing unpublished Profile Draft resumed. Closing this editor will keep the Draft.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "关闭" }));

    await waitFor(() => expect(screen.queryByRole("dialog", { name: "编辑 Resumed Profile" })).toBeNull());
    expect(mockFetch.mock.calls.some(([input, init]) => String(input) === "/api/drafts/profile-draft-1" && init?.method === "DELETE")).toBe(false);
    expect(researchProfileDraft).not.toBeNull();
  });

  it("duplicates a Profile's canonical settings into a new Draft", async () => {
    const created = vi.fn();
    render(<ResearchProfileCreateDialog profiles={[profileSummary]} sourceProfile={profile as unknown as ResearchProfile} onClose={() => undefined} onCreated={created} />);
    expect(screen.queryByLabelText("Initial Lens ID")).toBeNull();
    expect(screen.queryByLabelText("Initial Query")).toBeNull();
    expect(screen.queryByLabelText("New Profile schedule")).toBeNull();
    fireEvent.change(screen.getByLabelText("New Profile ID"), { target: { value: "continual-learning-copy" } });
    fireEvent.change(screen.getByLabelText("New Profile title"), { target: { value: "Continual Learning Copy" } });
    fireEvent.click(screen.getByRole("button", { name: "Create Draft" }));

    await waitFor(() => expect(created).toHaveBeenCalledTimes(1));
    const call = mockFetch.mock.calls.find(([input, init]) => String(input) === "/api/drafts" && init?.method === "POST");
    const body = JSON.parse(String(call?.[1]?.body));
    const draftProfile = parse(body.content);
    expect(draftProfile).toMatchObject({
      id: "continual-learning-copy",
      title: "Continual Learning Copy",
      lenses: profile.lenses,
      providers: profile.providers,
      context: profile.context,
      search: profile.search,
      schedule: profile.schedule,
      inbox: profile.inbox,
      ai_analysis: profile.ai_analysis,
    });
  });

  it("blocks Note creation until the suggested Section is resolved", async () => {
    const collectionDraftsPath = "/api/drafts?entity_type=collection&entity_id=continual-learning";
    const fetchNormally = mockFetch.getMockImplementation();
    let resolveCollectionDrafts: (() => void) | undefined;
    mockFetch.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input) === collectionDraftsPath) {
        return new Promise<Response>((resolve) => {
          resolveCollectionDrafts = () => resolve(jsonResponse([]));
        });
      }
      return fetchNormally!(input, init);
    });
    const onCreate = vi.fn();
    render(<ResearchCreateNoteDialog
      title="A New Regularization Method"
      busy={false}
      suggestedCollectionId="continual-learning"
      suggestedSection="Regularization"
      allowedCollectionIds={["continual-learning"]}
      onClose={() => undefined}
      onCreate={onCreate}
    />);

    await waitFor(() => {
      expect((screen.getByLabelText("Collection") as HTMLSelectElement).value).toBe("continual-learning");
    });
    const createButton = screen.getByRole("button", { name: "Create" });
    expect(createButton.hasAttribute("disabled")).toBe(true);
    expect(screen.getByText("Resolving suggested destination…")).toBeTruthy();
    fireEvent.click(createButton);
    expect(onCreate).not.toHaveBeenCalled();

    resolveCollectionDrafts?.();
    expect(await screen.findByText(/was preselected/)).toBeTruthy();
    expect((screen.getByLabelText("Section") as HTMLSelectElement).value).toBe("regularization");
    expect(createButton.hasAttribute("disabled")).toBe(false);
  });

  it("does not preselect a suggested Section when its title is ambiguous", async () => {
    responseCollection = {
      id: "continual-learning",
      title: "Continual Learning",
      description: null,
      status: "active",
      position: 0,
      nodes: [
        { id: "regularization-a", kind: "section", title: "Regularization", children: [] },
        { id: "regularization-b", kind: "section", title: "Regularization", children: [] },
      ],
    };
    render(<ResearchCreateNoteDialog title="A New Regularization Method" busy={false} suggestedCollectionId="continual-learning" suggestedSection="Regularization" allowedCollectionIds={["continual-learning"]} onClose={() => undefined} onCreate={() => undefined} />);

    await screen.findByText(/matches multiple sections/);
    expect((screen.getByLabelText("Collection") as HTMLSelectElement).value).toBe("continual-learning");
    expect((screen.getByLabelText("Section") as HTMLSelectElement).value).toBe("");
    expect(screen.getAllByRole("option", { name: "Regularization" })).toHaveLength(2);
  });

  it("allows manual destination choice when the suggested Section is missing", async () => {
    responseCollection = {
      ...responseCollection,
      nodes: [],
    };
    const onCreate = vi.fn();
    render(<ResearchCreateNoteDialog title="A New Regularization Method" busy={false} suggestedCollectionId="continual-learning" suggestedSection="Regularization" allowedCollectionIds={["continual-learning"]} onClose={() => undefined} onCreate={onCreate} />);

    expect(await screen.findByText(/was not found; choose a section manually/)).toBeTruthy();
    const createButton = screen.getByRole("button", { name: "Create" });
    expect(createButton.hasAttribute("disabled")).toBe(false);
    fireEvent.click(createButton);
    expect(onCreate).toHaveBeenCalledWith({
      document_type: "paper-note",
      template: "structured",
      collection_id: "continual-learning",
    });
  });

  it("queues custom Research dates as local calendar boundaries", async () => {
    const now = new Date();
    const localDate = (value: Date) => `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, "0")}-${String(value.getDate()).padStart(2, "0")}`;
    const start = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 3, 0, 0, 0, 0);
    const end = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1, 0, 0, 0, 0);
    const startDate = localDate(start);
    const endDate = localDate(end);
    const expectedStart = start.toISOString();
    const expectedEnd = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 0, 0, 0, 0).toISOString();
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Search Now" }));
    fireEvent.change(screen.getByLabelText("时间范围"), { target: { value: "custom" } });
    fireEvent.change(screen.getByLabelText("开始日期"), { target: { value: startDate } });
    fireEvent.change(screen.getByLabelText("结束日期"), { target: { value: endDate } });
    fireEvent.click(screen.getByRole("button", { name: "加入搜索队列" }));

    expect(await screen.findByText(/Search queued/)).toBeTruthy();
    const call = mockFetch.mock.calls.find(([input, init]) => String(input) === "/api/research/profiles/continual-learning/runs" && init?.method === "POST");
    expect(call).toBeTruthy();
    expect(JSON.parse(String(call?.[1]?.body))).toMatchObject({
      date_range: { mode: "custom", start: expectedStart, end: expectedEnd },
    });
  });

  it("requires an Additional Query Lens for multiple selected lenses and queues incremental search", async () => {
    responseProfileDetail = {
      ...profileDetail,
      profile: {
        ...profile,
        lenses: [...profile.lenses, { id: "replay", title: "Replay", enabled: true, priority: "medium", queries: ["experience replay"], include_terms: ["replay"], exclude_terms: [] }],
      },
    };
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Search Now" }));
    fireEvent.change(screen.getByLabelText("时间范围"), { target: { value: "incremental" } });
    fireEvent.change(screen.getByLabelText(/额外检索词/), { target: { value: "replay distillation" } });

    expect(screen.getByText("从已有的 Lens / Provider / Query Watermark 窗口检索；没有水位的新增 query 使用 Profile 初始回看天数。这是手动 Run，不会推进 scheduled Watermark。")).toBeTruthy();
    expect(screen.getByLabelText(/Additional Query Lens/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "加入搜索队列" }));
    expect(await screen.findByText("选择多个 Lens 时，请指定 Additional Query Lens。")).toBeTruthy();

    fireEvent.change(screen.getByLabelText(/Additional Query Lens/), { target: { value: "replay" } });
    fireEvent.click(screen.getByRole("button", { name: "加入搜索队列" }));
    expect(await screen.findByText(/Search queued/)).toBeTruthy();
    const call = mockFetch.mock.calls.find(([input, init]) => String(input) === "/api/research/profiles/continual-learning/runs" && init?.method === "POST");
    expect(JSON.parse(String(call?.[1]?.body))).toMatchObject({
      lenses: ["regularization", "replay"],
      date_range: { mode: "incremental" },
      additional_queries: ["replay distillation"],
      additional_query_lens: "replay",
    });
  });

  it("explains that discovery is paused when AI Analysis is disabled", async () => {
    responseProfileDetail = {
      ...profileDetail,
      profile: {
        ...profile,
        ai_analysis: { ...profile.ai_analysis, enabled: false },
      },
    };
    render(<App />);

    expect(await screen.findByText(
      "Research discovery and DeepSeek analysis are disabled · 自动与手动 Research Run 均已暂停；启用后从原 Watermark 继续。",
    )).toBeTruthy();
    expect(screen.getByRole("button", { name: "Search Now" }).hasAttribute("disabled")).toBe(true);
  });

  it("explains when all default Lenses are disabled but keeps temporary Search Now available", async () => {
    responseProfileDetail = {
      ...profileDetail,
      profile: {
        ...profile,
        lenses: profile.lenses.map((lens) => ({ ...lens, enabled: false })),
      },
    };
    render(<App />);

    expect(await screen.findByText(
      "No active default Lens · 自动发现当前不会执行",
    )).toBeTruthy();
    expect(screen.getByText("Search Now 仍可临时选择 Lens。")).toBeTruthy();
    const searchButton = screen.getByRole("button", { name: "Search Now" });
    expect(searchButton.hasAttribute("disabled")).toBe(false);
    fireEvent.click(searchButton);

    const searchForm = screen.getByText("Search Focus").closest("form");
    expect(searchForm).not.toBeNull();
    const lens = within(searchForm as HTMLElement).getByRole("checkbox", { name: /Regularization/ });
    expect((lens as HTMLInputElement).checked).toBe(false);
    fireEvent.click(lens);
    expect((lens as HTMLInputElement).checked).toBe(true);
  });

  it("blocks manual search when the Profile is disabled", async () => {
    responseProfileSummary = { ...profileSummary, enabled: false };
    responseProfileDetail = {
      ...profileDetail,
      profile: { ...profile, enabled: false },
      canonical_content: stringify({ ...profile, enabled: false }, { lineWidth: 0 }),
    };
    render(<App />);

    expect(await screen.findByText(
      "Profile disabled · 启用 Profile 后才能运行 Search Now。",
    )).toBeTruthy();
    expect(screen.getByRole("button", { name: "Search Now" }).hasAttribute("disabled")).toBe(true);
  });

  it("blocks manual search while the Profile is paused", async () => {
    responseProfileDetail = {
      ...profileDetail,
      runtime_state: {
        ...profileDetail.runtime_state!,
        paused_until: new Date(Date.now() + 86_400_000).toISOString(),
      },
    };
    render(<App />);

    expect(await screen.findByText(
      "Research paused · Resume Profile 后才能运行 Search Now。",
    )).toBeTruthy();
    expect(screen.getByRole("button", { name: "Search Now" }).hasAttribute("disabled")).toBe(true);
  });

  it("blocks manual search when the Inbox is full", async () => {
    const fullInbox = { new_count: 20, capacity: 20, remaining: 0 };
    responseProfileSummary = { ...profileSummary, inbox: fullInbox };
    responseProfileDetail = { ...profileDetail, inbox: fullInbox };
    render(<App />);

    expect(await screen.findByText("Inbox Full")).toBeTruthy();
    expect(screen.getByText("Inbox Full").parentElement?.textContent).toContain(
      "Inbox Full · 处理候选后才能运行 Search Now。",
    );
    expect(screen.getByRole("button", { name: "Search Now" }).hasAttribute("disabled")).toBe(true);
  });

  it("uses the local calendar date as the Pause date minimum", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-10-04T16:30:00.000Z"));
    render(<ResearchProfilePanel
      summary={profileSummary}
      detail={profileDetail}
      onRefresh={() => undefined}
      onQueued={() => undefined}
      onEditDefaults={() => undefined}
    />);
    fireEvent.click(screen.getByRole("button", { name: "Pause" }));

    const now = new Date();
    const localToday = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
    expect((screen.getByLabelText("暂停至指定日期") as HTMLInputElement).min).toBe(localToday);
  });

  it("edits Profile Defaults through autosaved Draft review and publish", async () => {
    const published = vi.fn();
    const user = userEvent.setup();
    render(<ResearchProfileDefaultsEditor
      profile={profile as unknown as ResearchProfile}
      canonicalContent={`# Keep this profile note.\n${stringify(profile, { lineWidth: 0 })}# Keep this trailing note.\n`}
      draftCreatedInThisFlow={false}
      onClose={() => undefined}
      onPublished={published}
    />);

    expect(await screen.findByRole("heading", { name: "编辑 Continual Learning" })).toBeTruthy();
    expect(screen.getByLabelText("Enable Research discovery + unattended DeepSeek analysis")).toBeTruthy();
    expect(screen.getByText(/Scheduled \/ Manual Run/)).toBeTruthy();
    expect(screen.getByText(/持续授权/)).toBeTruthy();
    expect(screen.getByText(/筛选词、breadth 和 Knowledge Context 的修改只影响后续 Research Run/)).toBeTruthy();
    fireEvent.click(screen.getByLabelText("Discovery Provider openalex"));
    fireEvent.click(screen.getByLabelText("Discovery Provider arxiv"));
    const lastDiscoveryProvider = screen.getByLabelText("Discovery Provider openalex") as HTMLInputElement;
    expect(lastDiscoveryProvider.checked).toBe(true);
    expect(lastDiscoveryProvider.disabled).toBe(true);
    fireEvent.click(lastDiscoveryProvider);
    expect(lastDiscoveryProvider.checked).toBe(true);
    fireEvent.click(screen.getByLabelText("Enrichment Provider openalex"));
    fireEvent.click(screen.getByLabelText("Enrichment Provider crossref"));
    fireEvent.change(screen.getByLabelText("Profile title"), { target: { value: "Continual Learning Research" } });
    fireEvent.change(screen.getByLabelText("Profile description"), { target: { value: "Updated research direction." } });
    fireEvent.change(screen.getByLabelText("New Lens ID"), { target: { value: "replay-methods" } });
    fireEvent.change(screen.getByLabelText("New Lens title"), { target: { value: "Replay Methods" } });
    fireEvent.change(screen.getByLabelText("Initial Query"), { target: { value: "replay continual learning" } });
    fireEvent.click(screen.getByRole("button", { name: "Add Lens" }));
    fireEvent.click(screen.getByRole("button", { name: "Remove Lens regularization" }));
    const queriesField = screen.getByLabelText(/Queries/) as HTMLTextAreaElement;
    expect(queriesField.value).toBe("replay continual learning");
    await user.clear(queriesField);
    await user.type(queriesField, "query one");
    await user.keyboard("{Enter}");
    expect(queriesField.value).toBe("query one\n");
    await user.type(queriesField, "query two");
    await user.tab();
    expect(screen.getByRole("option", { name: "Selected Collections and Documents" })).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Dynamic Retrieval scope"), { target: { value: "selected-context" } });

    await waitFor(() => {
      expect(mockFetch.mock.calls.some(([input, init]) => String(input) === "/api/drafts" && init?.method === "POST")).toBe(true);
    }, { timeout: 3000 });
    const draftContent = String(researchProfileDraft?.content);
    expect(draftContent).toContain("title: Continual Learning Research");
    expect(draftContent).toContain("description: Updated research direction.");
    expect(draftContent).toContain("id: replay-methods");
    expect(draftContent).toContain("title: Replay Methods");
    expect(draftContent).not.toContain("id: regularization");
    expect(parse(draftContent)).toMatchObject({ lenses: [{ queries: ["query one", "query two"] }] });
    expect(draftContent).toContain("scope: selected-context");
    expect(draftContent).toContain("max_analyses_per_run: 30");
    expect(parse(draftContent)).toMatchObject({
      providers: { discovery: ["openalex"], enrichment: ["openalex", "crossref"] },
    });
    expect(draftContent).toContain("# Keep this profile note.");
    expect(draftContent).toContain("# Keep this trailing note.");
    expect(draftContent.indexOf("schema_version:")).toBeLessThan(draftContent.indexOf("id:"));

    fireEvent.click(screen.getByRole("button", { name: "Review Diff" }));
    expect(await screen.findByText("Profile Draft preflight 通过。")).toBeTruthy();
    expect(screen.getByRole("region", { name: "Profile changes" }).textContent).toContain("query two");
    fireEvent.click(screen.getByRole("button", { name: "Publish Defaults" }));

    await waitFor(() => {
      expect(mockFetch.mock.calls.some(([input, init]) => String(input) === "/api/publish" && init?.method === "POST")).toBe(true);
    });
    expect(published).toHaveBeenCalledWith([]);
  });

  it("filters pinned Documents by title or ID without losing selection", async () => {
    responseDocuments = [
      { id: "alpha-notes", title: "Alpha Research Notes" },
      { id: "beta-notes", title: "Beta Research Notes" },
    ];
    render(<ResearchProfileDefaultsEditor
      profile={profile as unknown as ResearchProfile}
      canonicalContent={stringify(profile, { lineWidth: 0 })}
      draftCreatedInThisFlow={false}
      onClose={() => undefined}
      onPublished={() => undefined}
    />);

    const alphaCheckbox = await screen.findByRole("checkbox", { name: "Alpha Research Notes" }) as HTMLInputElement;
    fireEvent.click(alphaCheckbox);
    const filter = screen.getByRole("searchbox", { name: "Filter Pinned Documents" });
    fireEvent.change(filter, { target: { value: "beta" } });
    expect(screen.queryByRole("checkbox", { name: "Alpha Research Notes" })).toBeNull();
    expect(screen.getByRole("checkbox", { name: "Beta Research Notes" })).toBeTruthy();

    fireEvent.change(filter, { target: { value: "alpha-notes" } });
    expect((screen.getByRole("checkbox", { name: "Alpha Research Notes" }) as HTMLInputElement).checked).toBe(true);
  });

  it("requires a reactivation choice before publishing an enabled Profile with an old watermark", async () => {
    responseProfileDetail = {
      ...profileDetail,
      profile: { ...profile, enabled: false },
      canonical_content: stringify({ ...profile, enabled: false }, { lineWidth: 0 }),
    };
    responseProfileSummary = { ...profileSummary, enabled: false };
    reactivationReviewResponse = {
      required: true,
      triggers: ["profile_enabled"],
      streams: [{ lens_id: "regularization", provider: "arxiv", query_key: "a".repeat(64), query_text: "fisher information" }],
      max_catchup_days: 30,
      strategies: ["last_window", "all", "from_now"],
    };
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Edit Defaults" }));
    fireEvent.click(await screen.findByLabelText("Enable Research Profile"));
    fireEvent.click(screen.getByRole("button", { name: "Review Diff" }));

    expect(await screen.findByRole("group", { name: "Reactivation Review" })).toBeTruthy();
    const publishButton = screen.getByRole("button", { name: "Publish Defaults" });
    expect(publishButton.hasAttribute("disabled")).toBe(true);
    fireEvent.click(screen.getByLabelText("Catch up last 30 days"));
    expect(publishButton.hasAttribute("disabled")).toBe(false);
    fireEvent.click(publishButton);

    await waitFor(() => {
      const call = mockFetch.mock.calls.find(([input, init]) => String(input) === "/api/publish" && init?.method === "POST");
      expect(JSON.parse(String(call?.[1]?.body))).toEqual({
        draft_id: "profile-draft-1",
        expected_revision: 1,
        reactivation_strategy: "last_window",
      });
    });
  });

  it("labels a re-enabled Discovery Provider in Reactivation Review", async () => {
    reactivationReviewResponse = {
      required: true,
      triggers: ["provider_enabled:openalex"],
      streams: [{ lens_id: "regularization", provider: "openalex", query_key: "b".repeat(64), query_text: "fisher information" }],
      max_catchup_days: 30,
      strategies: ["last_window", "all", "from_now"],
    };
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Edit Defaults" }));
    fireEvent.click(await screen.findByLabelText("Discovery Provider openalex"));
    fireEvent.click(await screen.findByRole("button", { name: "Review Diff" }));

    expect(await screen.findByText("启用 Discovery Provider：OpenAlex")).toBeTruthy();
  });

  it("opens the Source Draft in the Unified Workspace", async () => {
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Save Source" }));

    expect(await screen.findByText("Source Workspace")).toBeTruthy();
    expect(window.location.pathname).toBe("/sources/research-paper");
    expect(window.location.search).toBe("?edit=1");
  });

  it("creates a structured note group and enters batch Workspace review", async () => {
    responseProfileDetail = {
      ...profileDetail,
      profile: { ...profile, context: { ...profile.context, collections: ["continual-learning"] } },
    };
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Create Note" }));
    expect(await screen.findByRole("heading", { name: "Create Research Note" })).toBeTruthy();
    await screen.findByRole("option", { name: "Regularization" });
    expect((screen.getByLabelText("Collection") as HTMLSelectElement).value).toBe("continual-learning");
    await waitFor(() => expect((screen.getByLabelText("Section") as HTMLSelectElement).value).toBe("regularization"));
    fireEvent.change(screen.getByLabelText("Collection"), { target: { value: "continual-learning" } });
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
  search: { breadth: "balanced", initial_lookback_days: 30, max_catchup_days: 30, max_candidates_per_run: 10, max_analyses_per_run: 30 },
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
  manual_queue: { pending: 0, claimed: 0 },
  latest_run: null,
};

const profileDetail = {
  profile,
  canonical_content: stringify(profile, { lineWidth: 0 }),
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
  suggested_collection: "continual-learning", suggested_section: "Regularization",
};

const candidateListItem = { candidate, work, analysis, recommended_score: 0.84 };
const candidateDetail = {
  candidate: { ...candidate, first_viewed_at: "2026-10-03T00:00:00+00:00", last_viewed_at: "2026-10-03T00:00:00+00:00" },
  work,
  analysis: { id: "analysis-1", work_id: work.id, profile_id: profile.id, input_hash: "sha256:abc", outcome: "surface", analysis, provider: "deepseek", model: "deepseek-chat", prompt_version: "research-candidate-analysis-v1", analysis_version: 1, context_entity_ids: ["gem-sgd"], input_context: { analysis_version: 1, prompt_version: "research-candidate-analysis-v1", provider: "deepseek", model: "deepseek-chat", work: { ...work }, profile: { id: profile.id, title: profile.title, description: profile.description, breadth: "balanced", breadth_policy: "Include work related to the core topic and adjacent methods." }, matched_lens: { ...profile.lenses[0] }, knowledge_context: { focus_query: "fisher information catastrophic forgetting", budget: 5, omitted_count: 0, cards: [{ entity_type: "document", entity_id: "gem-sgd", title: "Elastic Weight Consolidation", review_status: "reviewed", topics: ["continual-learning"], domains: [], relevant_sections: [{ heading: "Method", excerpt: "Snapshot excerpt used at analysis time." }], metadata: {}, pinned: true, retrieval_score: 0.9 }] } }, analyzed_at: "2026-10-03T00:00:00+00:00" },
  discoveries: [{ id: "discovery-1", work_id: work.id, profile_id: profile.id, lens_id: "regularization", provider: "arxiv", provider_record_id: "2501.00001", query_key: "query-key", query_text: "fisher information catastrophic forgetting", metadata: {}, discovered_at: "2026-10-03T00:00:00+00:00" }],
  knowledge_relations: analysis.existing_relations,
  linked_entities: [{ entity_type: "source", entity_id: "published-paper", relation_type: "source", created_at: "2026-10-03T00:00:00+00:00" }],
  pending_links: [],
};
