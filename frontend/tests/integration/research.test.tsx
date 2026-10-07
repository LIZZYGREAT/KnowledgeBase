import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { parse, stringify } from "yaml";
import App from "../../src/App";
import { ResearchProfilePanel } from "../../src/ResearchProfile";
import { ResearchProfileDefaultsEditor } from "../../src/ResearchProfileDefaultsEditor";
import { ResearchProfileCreateDialog } from "../../src/ResearchProfileCreateDialog";
import { ResearchCandidateCard, ResearchCandidateDrawer, ResearchCreateNoteDialog } from "../../src/ResearchCandidate";
import { ResearchRunDrawer, ResearchRunList } from "../../src/ResearchRun";
import type { ResearchCandidateListItem, ResearchProfile, ResearchRun, ResearchRunStatus } from "../../src/api";

vi.mock("../../src/Workspace", async () => {
  const React = await import("react");
  return {
    WorkspacePage: (props: { openMetadataOnLoad?: boolean }) => React.createElement(
      "div",
      null,
      props.openMetadataOnLoad ? "Source Metadata Editor" : "Source Workspace",
    ),
  };
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
  let restoreCapacityFull = false;
  let candidateRestored = false;

  beforeEach(() => {
    responseProfileDetail = profileDetail;
    responseProfileSummary = profileSummary;
    responseCandidateDetail = candidateDetail;
    responseCollection = { id: "continual-learning", title: "Continual Learning", description: null, status: "active", position: 0, nodes: [{ id: "regularization", kind: "section", title: "Regularization", children: [] }] };
    responseDocuments = [];
    researchProfileDraft = null;
    createDraftCreatedInThisFlow = true;
    restoreCapacityFull = false;
    candidateRestored = false;
    window.history.replaceState({}, "", "/research");
    vi.spyOn(window, "scrollTo").mockImplementation(() => undefined);
    mockFetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/api/collections?status=active") return jsonResponse([{ id: "continual-learning", title: "Continual Learning", description: null, status: "active", position: 0, node_count: 1, entity_count: 0, document_count: 0 }]);
      if (path === "/api/terms/fisher-information") return jsonResponse({ id: "fisher-information", title: "Fisher Information" });
      if (path === "/api/sources/published-paper") return jsonResponse({ id: "published-paper", title: "Published Paper" });
      if (path === "/api/collections/continual-learning") return jsonResponse(responseCollection);
      if (path === "/api/drafts?entity_type=collection&entity_id=continual-learning") return jsonResponse([]);
      if (path === "/api/documents?limit=100&offset=0") return jsonResponse(responseDocuments);
      if (path === "/api/research/profiles") return jsonResponse([responseProfileSummary]);
      if (path === "/api/research/profiles/continual-learning") return jsonResponse(responseProfileDetail);
      if (path === "/api/research/profiles/continual-learning/resume" && init?.method === "POST") return jsonResponse({});
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
      if (path === "/api/publish" && init?.method === "POST") return jsonResponse({ draft_id: "profile-draft-1", entity_type: "research_profile", entity_id: "continual-learning", commit_revision: "def456", warnings: [] });
      if (path.startsWith("/api/research/candidates?") && path.includes("status=new")) return jsonResponse({ candidates: [candidateListItem], count: 1, offset: 0, limit: 50 });
      if (path.startsWith("/api/research/candidates?") && path.includes("status=dismissed")) return jsonResponse({ candidates: candidateRestored ? [] : [{ ...candidateListItem, candidate: { ...candidate, status: "dismissed" } }], count: candidateRestored ? 0 : 1, offset: 0, limit: 50 });
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
      if (path === "/api/research/candidates/candidate-1/dismiss" && init?.method === "POST") {
        const body = JSON.parse(String(init.body));
        return jsonResponse({ ...candidate, status: "dismissed", dismiss_reason: body.reason ?? null });
      }
      if (path === "/api/research/candidates/candidate-1/restore" && init?.method === "POST") {
        if (restoreCapacityFull) return jsonResponse({ detail: "Research Inbox is full" }, 409);
        candidateRestored = true;
        return jsonResponse({ ...candidate, status: "new", dismiss_reason: null, decided_at: null });
      }
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
      source_match_candidates: [
        { id: "source-one", title: "A New Regularization Method", matched_by: ["title_author_year"], conflicts: [] },
        { id: "source-two", title: "A New Regularization Method (2017)", matched_by: ["title_author_year"], conflicts: [] },
      ],
    };
    render(<App />);

    expect(screen.getByRole("button", { name: /Research/ }).getAttribute("aria-current")).toBe("page");
    expect(await screen.findByText("Discoveries", {}, { timeout: 5000 })).toBeTruthy();
    expect(await screen.findByRole("heading", { name: "A New Regularization Method" }, { timeout: 5000 })).toBeTruthy();
    const candidateCard = screen.getByRole("heading", { name: "A New Regularization Method" }).closest(".research-candidate-card") as HTMLElement;
    expect(within(candidateCard).getByText("Readiness")).toBeTruthy();
    expect(within(candidateCard).getByText(/Why now: It connects a known foundation/)).toBeTruthy();
    expect(within(candidateCard).getByText("Discovered Terms: 2")).toBeTruthy();
    expect(within(candidateCard).getByRole("button", { name: /Review in Terms/ })).toBeTruthy();
    fireEvent.click(within(candidateCard).getByRole("button", { name: "中文" }));
    expect(screen.getByText("关联知识")).toBeTruthy();
    expect(screen.getByText("为什么值得读")).toBeTruthy();
    expect(screen.queryByText("What may be new")).toBeNull();
    expect(screen.queryByText("Relevance: High")).toBeNull();
    expect(screen.queryByText("Library novelty: Medium")).toBeNull();
    expect(screen.queryByText(/排序信号/)).toBeNull();
    expect(screen.queryByText("73% library novelty")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: /Why this candidate/ }));
    expect(await screen.findByRole("heading", { name: "Why this candidate" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Readiness" })).toBeTruthy();
    expect(screen.getByText("Known prerequisites")).toBeTruthy();
    expect(screen.getByText("Missing prerequisites")).toBeTruthy();
    expect(screen.getAllByRole("button", { name: /Review in Terms/ })).toHaveLength(2);
    expect(screen.getByRole("alert").textContent).toContain("为避免重复记录");
    expect(screen.getByText("可能已存在 2 个 Source")).toBeTruthy();
    expect(screen.getByText("有多条 Source 同时匹配标题、第一作者和年份，请检查是否存在重复 Source。")).toBeTruthy();
    expect(screen.getAllByRole("button", { name: "Open to fix" })).toHaveLength(2);
    const technical = screen.getByText("Technical provenance").closest("details") as HTMLDetailsElement;
    expect(technical.open).toBe(false);
    const modelSignals = screen.getByText("Model signals").closest("details") as HTMLDetailsElement;
    expect(modelSignals.open).toBe(false);
    fireEvent.click(screen.getByText("Technical provenance"));
    expect(technical.open).toBe(true);
    expect(modelSignals.open).toBe(false);
    fireEvent.click(screen.getByText("Model signals"));
    expect(screen.getByText("These are uncalibrated model signals. They are not paper quality scores or probabilities.")).toBeTruthy();
    expect(screen.getByText("Recommended ranking score")).toBeTruthy();
    expect(screen.getByText("0.84")).toBeTruthy();
    expect(screen.getByText("Matched query")).toBeTruthy();
    expect(screen.getByText("research-candidate-analysis-v1")).toBeTruthy();
    expect(screen.getAllByText("fisher information catastrophic forgetting").length).toBeGreaterThan(1);
    expect(screen.getByRole("heading", { name: "Analysis-time context" })).toBeTruthy();
    expect(screen.getByText("Snapshot excerpt used at analysis time.")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Current knowledge links" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Suggested destination" })).toBeTruthy();
    expect(screen.getByText("Collection · continual-learning")).toBeTruthy();
    expect(await screen.findByText("Fisher Information")).toBeTruthy();
    expect(await screen.findByText("Source · Published Paper")).toBeTruthy();
    fireEvent.click(await screen.findByRole("button", { name: "Edit note" }));
    fireEvent.change(await screen.findByRole("textbox", { name: "Candidate note" }), { target: { value: "Compare with replay-based methods." } });
    fireEvent.click(screen.getByRole("button", { name: "Save note" }));
    await waitFor(() => expect(mockFetch.mock.calls.some(([input, init]) => String(input) === "/api/research/candidates/candidate-1/note" && init?.method === "PATCH")).toBe(true));
    const noteCall = mockFetch.mock.calls.find(([input, init]) => String(input) === "/api/research/candidates/candidate-1/note" && init?.method === "PATCH");
    expect(JSON.parse(String(noteCall?.[1]?.body))).toEqual({ note: "Compare with replay-based methods." });
    expect(await screen.findByText("Compare with replay-based methods.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    fireEvent.click(await screen.findByRole("button", { name: "Shortlist" }));
    await waitFor(() => expect(mockFetch.mock.calls.some(([input, init]) => String(input) === "/api/research/candidates/candidate-1/shortlist" && init?.method === "POST")).toBe(true));
    const shortlistCall = mockFetch.mock.calls.find(([input, init]) => String(input) === "/api/research/candidates/candidate-1/shortlist" && init?.method === "POST");
    expect(JSON.parse(String(shortlistCall?.[1]?.body))).toEqual({});
    expect(screen.queryByRole("heading", { name: "Shortlist candidate" })).toBeNull();
  }, 10_000);

  it("opens the conflicting canonical Source directly for metadata repair", () => {
    const openEntity = vi.fn();
    render(<ResearchCandidateDrawer
      detail={{
        ...candidateDetail,
        conversion_blocker: "ambiguous_source",
        source_match_candidates: [{ id: "source-one", title: "A New Regularization Method", matched_by: ["doi"], conflicts: [{ field: "openalex_id", existing_value: "W111", discovered_value: "W222" }] }],
      }}
      profile={profile as unknown as ResearchProfile}
      language="en"
      onLanguageChange={() => undefined}
      noteBusy={false}
      noteError=""
      onClose={() => undefined}
      onOpenEntity={openEntity}
      onSaveSource={() => undefined}
      onSaveNote={() => undefined}
    />);
    fireEvent.click(screen.getByRole("button", { name: "Open to fix" }));
    expect(openEntity).toHaveBeenCalledWith("/sources/source-one?edit=1");
    expect(screen.getByText("冲突：OpenAlex ID")).toBeTruthy();
    expect(screen.getByText("现有：W111")).toBeTruthy();
    expect(screen.getByText("本次发现：W222")).toBeTruthy();
  });

  it("routes the ambiguity repair link to Source metadata editing", async () => {
    responseCandidateDetail = {
      ...candidateDetail,
      conversion_blocker: "ambiguous_source",
      source_match_candidates: [{ id: "source-one", title: "A New Regularization Method", matched_by: ["title_author_year"], conflicts: [] }],
    };
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: /Why this candidate/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Open to fix" }));
    expect(await screen.findByText("Source Metadata Editor")).toBeTruthy();
  });

  it("queues a manual run without executing it in the page request", async () => {
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Search Now" }));
    fireEvent.change(screen.getByLabelText(/额外检索词/), { target: { value: "dynamic fisher continual learning" } });
    fireEvent.click(screen.getByRole("button", { name: "加入搜索队列" }));

    expect(await screen.findByText("搜索已加入队列。")).toBeTruthy();
    expect(await screen.findByText("1 manual search queued")).toBeTruthy();
    const call = mockFetch.mock.calls.find(([input, init]) => String(input) === "/api/research/profiles/continual-learning/runs" && init?.method === "POST");
    expect(call).toBeTruthy();
    const body = JSON.parse(String(call?.[1]?.body));
    expect(body).toMatchObject({ lenses: ["regularization"], breadth: "balanced", additional_queries: ["dynamic fisher continual learning"], additional_query_lens: "regularization" });
    expect(mockFetch.mock.calls.some(([input]) => String(input).includes("/api/research/runs/") && !String(input).includes("offset="))).toBe(false);
  });

  it("restores a dismissed candidate and stays in History until the user opens the Inbox", async () => {
    render(<App />);
    fireEvent.click(await screen.findByRole("tab", { name: "History" }));
    const restoreButton = await screen.findByRole("button", { name: "Restore to Inbox" });
    expect(screen.getByText("Dismissed", { selector: ".chip" }).className).toBe("chip chip-neutral");
    fireEvent.click(restoreButton);

    await waitFor(() => expect(mockFetch.mock.calls.some(([input, init]) => String(input) === "/api/research/candidates/candidate-1/restore" && init?.method === "POST")).toBe(true));
    expect((await screen.findByRole("tab", { name: "History" })).getAttribute("aria-selected")).toBe("true");
    expect(await screen.findByText("已恢复到 Inbox。")).toBeTruthy();
    await waitFor(() => expect(screen.queryByRole("heading", { name: "A New Regularization Method" })).toBeNull());
    fireEvent.click(screen.getByRole("button", { name: "View Inbox" }));
    const newTab = await screen.findByRole("tab", { name: /New/ });
    expect(newTab.getAttribute("aria-selected")).toBe("true");
    expect(await screen.findByRole("heading", { name: "A New Regularization Method" })).toBeTruthy();
  });

  it("keeps a dismissed candidate in History when Restore is blocked by a full Inbox", async () => {
    restoreCapacityFull = true;
    render(<App />);
    fireEvent.click(await screen.findByRole("tab", { name: "History" }));
    fireEvent.click(await screen.findByRole("button", { name: "Restore to Inbox" }));

    expect(await screen.findByText("Research Inbox is full")).toBeTruthy();
    expect(screen.getByRole("tab", { name: "History" }).getAttribute("aria-selected")).toBe("true");
    expect(screen.getByRole("heading", { name: "A New Regularization Method" })).toBeTruthy();
  });

  it("checks Source ambiguity before opening the Create Note form", async () => {
    responseCandidateDetail = {
      ...candidateDetail,
      conversion_blocker: "ambiguous_source",
      source_match_candidates: [{ id: "source-one", title: "A New Regularization Method", matched_by: ["doi"], conflicts: [{ field: "openalex_id", existing_value: "W111", discovered_value: "W222" }] }],
    };
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Create Note" }));

    expect(await screen.findByRole("heading", { name: "Why this candidate" })).toBeTruthy();
    expect(screen.getByText("请先修复下面显示的 Source 冲突，再创建笔记或保存 Source。为避免重复记录，当前转换操作已阻止。")).toBeTruthy();
    expect(screen.getByText("冲突：OpenAlex ID")).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "Create Research Note" })).toBeNull();
  });

  it("dismisses one candidate immediately without a reason prompt", async () => {
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Dismiss" }));
    await waitFor(() => expect(mockFetch.mock.calls.some(([input, init]) => String(input) === "/api/research/candidates/candidate-1/dismiss" && init?.method === "POST")).toBe(true));
    const singleDismiss = mockFetch.mock.calls.find(([input, init]) => String(input) === "/api/research/candidates/candidate-1/dismiss" && init?.method === "POST");
    expect(JSON.parse(String(singleDismiss?.[1]?.body))).toEqual({});
    expect(screen.queryByRole("heading", { name: "Dismiss candidate" })).toBeNull();
  });

  it("keeps bulk shortlist confirmation while single-candidate shortlist is immediate", async () => {
    render(<App />);
    fireEvent.click(await screen.findByRole("checkbox", { name: "选择 A New Regularization Method" }));
    fireEvent.click(screen.getByRole("button", { name: "Shortlist selected" }));
    expect(await screen.findByRole("heading", { name: "Shortlist candidate" })).toBeTruthy();
    expect(mockFetch.mock.calls.some(([input, init]) => String(input) === "/api/research/candidates/candidate-1/shortlist" && init?.method === "POST")).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Confirm Shortlist" }));
    await waitFor(() => expect(mockFetch.mock.calls.some(([input, init]) => String(input) === "/api/research/candidates/candidate-1/shortlist" && init?.method === "POST")).toBe(true));
  });

  it("keeps bulk dismissal confirmation and makes its reason optional", async () => {
    render(<App />);
    fireEvent.click(await screen.findByRole("checkbox", { name: "选择 A New Regularization Method" }));
    fireEvent.click(screen.getByRole("button", { name: "Dismiss selected" }));
    expect(await screen.findByRole("heading", { name: "Dismiss candidate" })).toBeTruthy();
    expect((screen.getByRole("combobox", { name: "Reason (optional)" }) as HTMLSelectElement).value).toBe("");
    fireEvent.click(screen.getByRole("button", { name: "Confirm Dismiss" }));
    await waitFor(() => expect(mockFetch.mock.calls.filter(([input, init]) => String(input) === "/api/research/candidates/candidate-1/dismiss" && init?.method === "POST").length).toBeGreaterThan(0));
    const bulkDismiss = mockFetch.mock.calls.filter(([input, init]) => String(input) === "/api/research/candidates/candidate-1/dismiss" && init?.method === "POST").at(-1);
    expect(JSON.parse(String(bulkDismiss?.[1]?.body))).toEqual({});
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
    const technical = within(inspector).getByText("Technical details").closest("details") as HTMLDetailsElement;
    expect(technical.open).toBe(false);
    fireEvent.click(within(inspector).getByText("Technical details"));
    expect(within(inspector).getByText("Lens B")).toBeTruthy();
    expect(within(inspector).queryByText("Lens A")).toBeNull();
    expect(within(inspector).queryByText("Lens C")).toBeNull();
  });

  it("shows run outcomes and issues before collapsing pipeline diagnostics", () => {
    const run = {
      id: "run-summary",
      trigger: "manual",
      status: "partial",
      started_at: "2026-10-04T00:00:00+00:00",
      finished_at: "2026-10-04T00:01:05+00:00",
      fetched_count: 42,
      surfaced_count: 4,
      profile_id: profile.id,
      request_id: null,
      profile_content_hash: "sha256:abc",
      effective_config: {},
      new_work_count: 8,
      duplicate_count: 2,
      deterministic_filtered_count: 3,
      analysis_attempt_count: 4,
      analyzed_count: 4,
      analysis_counts_known: true,
      provider_summary: {},
      error_summary: "OpenAlex timed out after retry.",
    } satisfies ResearchRun;
    render(<ResearchRunDrawer run={run} onClose={() => undefined} />);
    expect(screen.getByText("42")).toBeTruthy();
    expect(screen.getByText("Results checked")).toBeTruthy();
    expect(screen.getByText("8")).toBeTruthy();
    expect(screen.getByText("New works")).toBeTruthy();
    const overview = screen.getByRole("dialog", { name: "Research Run" }).querySelector(".research-run-overview") as HTMLElement;
    expect(within(overview).getByText("4")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Run issues" })).toBeTruthy();
    expect(screen.getByText("OpenAlex timed out after retry.")).toBeTruthy();
    expect((screen.getByText("Technical details").closest("details") as HTMLDetailsElement).open).toBe(false);
  });

  it("renders normal Run flow-control states without failure tones", () => {
    const statuses: Array<[ResearchRunStatus, string, string]> = [
      ["success", "green", "✓"],
      ["running", "blue", "◷"],
      ["partial", "amber", "·"],
      ["skipped_paused", "amber", "·"],
      ["skipped_disabled", "amber", "·"],
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

  it("defaults each candidate to English and keeps language choices independent", () => {
    const secondItem = {
      ...candidateListItem,
      candidate: { ...candidateListItem.candidate, id: "candidate-2" },
      work: { ...candidateListItem.work, title: "Second Candidate" },
      analysis: { ...analysis, summary: "B English summary", summary_zh: "B 中文摘要" },
    } as ResearchCandidateListItem;
    render(<>
      <ResearchCandidateCard item={candidateListItem as ResearchCandidateListItem} profile={profile as ResearchProfile} selected={false} selectable={false} busy={false} onSelect={() => undefined} onDetails={() => undefined} onShortlist={() => undefined} onDismiss={() => undefined} onRestore={() => undefined} onCreateNote={() => undefined} />
      <ResearchCandidateCard item={secondItem} profile={profile as ResearchProfile} selected={false} selectable={false} busy={false} onSelect={() => undefined} onDetails={() => undefined} onShortlist={() => undefined} onDismiss={() => undefined} onRestore={() => undefined} onCreateNote={() => undefined} />
    </>);

    const groups = screen.getAllByRole("group", { name: "Candidate language" });
    expect(groups).toHaveLength(2);
    expect(within(groups[0]).getByRole("button", { name: "EN" }).getAttribute("aria-pressed")).toBe("true");
    expect(within(groups[1]).getByRole("button", { name: "EN" }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByText("A new parameter importance estimation method for continual learning.")).toBeTruthy();
    expect(screen.getByText("B English summary")).toBeTruthy();

    fireEvent.click(within(groups[0]).getByRole("button", { name: "中文" }));
    expect(screen.getByText("这篇论文提出一种新的持续学习参数重要性估计方法。")).toBeTruthy();
    expect(screen.getByText("B English summary")).toBeTruthy();
    expect(within(groups[0]).getByRole("button", { name: "中文" }).getAttribute("aria-pressed")).toBe("true");
    expect(within(groups[1]).getByRole("button", { name: "EN" }).getAttribute("aria-pressed")).toBe("true");
    expect(window.localStorage.getItem("knowledgebase.research-language")).toBeNull();
  });

  it("opens the detail drawer in its card language and keeps both controls in sync", async () => {
    render(<App />);
    const card = await screen.findByRole("heading", { name: "A New Regularization Method" }).then((heading) => heading.closest(".research-candidate-card") as HTMLElement);
    fireEvent.click(within(card).getByRole("button", { name: "中文" }));
    expect(within(card).getByText("这篇论文提出一种新的持续学习参数重要性估计方法。")).toBeTruthy();
    fireEvent.click(within(card).getByRole("button", { name: /Why this candidate/ }));

    const drawer = await screen.findByRole("dialog", { name: "Why this candidate" });
    expect(within(drawer).getByText("这篇论文提出一种新的持续学习参数重要性估计方法。")).toBeTruthy();
    expect(within(drawer).getByRole("button", { name: "中文" }).getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(within(drawer).getByRole("button", { name: "EN" }));
    expect(within(drawer).getByText("A new parameter importance estimation method for continual learning.")).toBeTruthy();
    expect(within(card).getByText("A new parameter importance estimation method for continual learning.")).toBeTruthy();
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
      onRestore={() => undefined}
      onCreateNote={() => undefined}
    />);

    fireEvent.click(screen.getByRole("button", { name: "中文" }));
    expect(screen.getByText("为什么值得读")).toBeTruthy();
    expect(screen.getByText("将其自适应估计结果与 EWC 进行比较。")).toBeTruthy();
  });

  it("falls back to English analysis for older candidates without Chinese fields", () => {
    const legacyAnalysis = Object.fromEntries(Object.entries(analysis).filter(([key]) => !key.endsWith("_zh")));
    render(<ResearchCandidateCard
      item={{ ...candidateListItem, analysis: legacyAnalysis } as ResearchCandidateListItem}
      profile={profile as ResearchProfile}
      selected={false}
      selectable={false}
      busy={false}
      onSelect={() => undefined}
      onDetails={() => undefined}
      onShortlist={() => undefined}
      onDismiss={() => undefined}
      onRestore={() => undefined}
      onCreateNote={() => undefined}
    />);

    expect(screen.getByText("A new parameter importance estimation method for continual learning.")).toBeTruthy();
    expect(screen.getByText("It matches the regularization Lens and studies parameter importance.")).toBeTruthy();
    expect(screen.getByText("Compare its adaptive estimates against EWC.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "中文" }));
    expect(screen.getByText("此历史候选暂无中文分析")).toBeTruthy();
    expect(screen.getByText("A new parameter importance estimation method for continual learning.")).toBeTruthy();
  });

  it("keeps core Chinese analysis available and falls back per untranslated relation", () => {
    const untranslatedRelation = {
      ...analysis.existing_relations[0],
      entity_id: "second-term",
      reason: "This relation has an English-only explanation.",
      reason_zh: null,
    };
    const partiallyTranslatedAnalysis = {
      ...analysis,
      existing_relations: [analysis.existing_relations[0], untranslatedRelation],
    };
    const partialDetail = {
      ...candidateDetail,
      analysis: { ...candidateDetail.analysis, analysis: partiallyTranslatedAnalysis },
      knowledge_relations: partiallyTranslatedAnalysis.existing_relations,
    };
    const { container } = render(<>
      <ResearchCandidateCard
        item={{ ...candidateListItem, analysis: partiallyTranslatedAnalysis } as ResearchCandidateListItem}
        profile={profile as ResearchProfile}
        selected={false}
        selectable={false}
        busy={false}
        onSelect={() => undefined}
        onDetails={() => undefined}
        onShortlist={() => undefined}
        onDismiss={() => undefined}
        onRestore={() => undefined}
        onCreateNote={() => undefined}
      />
      <ResearchCandidateDrawer
        detail={partialDetail}
        profile={profile as ResearchProfile}
        language="zh"
        onLanguageChange={() => undefined}
        noteBusy={false}
        noteError=""
        onClose={() => undefined}
        onOpenEntity={() => undefined}
        onSaveSource={() => undefined}
        onSaveNote={() => undefined}
      />
    </>);

    const card = container.querySelector(".research-candidate-card") as HTMLElement;
    const drawer = screen.getByRole("dialog", { name: "Why this candidate" });
    fireEvent.click(within(card).getByRole("button", { name: "中文" }));
    expect(within(card).getByText("这篇论文提出一种新的持续学习参数重要性估计方法。")).toBeTruthy();
    expect(within(drawer).getByText("这篇论文提出一种新的持续学习参数重要性估计方法。")).toBeTruthy();
    expect(screen.queryByText("此历史候选暂无中文分析")).toBeNull();
    const relationRows = [...container.querySelectorAll(".research-related-row small")].map((row) => row.textContent ?? "");
    expect(relationRows.some((text) => text.includes("This relation has an English-only explanation."))).toBe(true);
  });

  it("creates a Research Profile from name and focus, generating stable default identifiers", async () => {
    const created = vi.fn();
    render(<ResearchProfileCreateDialog profiles={[profileSummary]} sourceProfile={null} onClose={() => undefined} onCreated={created} />);
    fireEvent.change(screen.getByLabelText("New Profile title"), { target: { value: "3D Gaussian Splatting" } });
    fireEvent.change(screen.getByLabelText("New Profile description"), { target: { value: "New view synthesis work." } });
    fireEvent.change(screen.getByLabelText("Initial Query"), { target: { value: "continual learning regularization" } });
    expect(screen.queryByLabelText("New Profile schedule")).toBeNull();
    expect(screen.queryByLabelText("New Profile breadth")).toBeNull();
    expect(screen.queryByLabelText("New Profile inbox cap")).toBeNull();
    fireEvent.click(screen.getByText("Advanced identifiers"));
    expect((screen.getByLabelText("New Profile ID") as HTMLInputElement).value).toBe("3d-gaussian-splatting");
    expect((screen.getByLabelText("Initial Lens ID") as HTMLInputElement).value).toBe("main");
    fireEvent.click(screen.getByRole("button", { name: "Create Research Profile" }));

    await waitFor(() => expect(created).toHaveBeenCalledTimes(1));
    const call = mockFetch.mock.calls.find(([input, init]) => String(input) === "/api/drafts" && init?.method === "POST");
    const body = JSON.parse(String(call?.[1]?.body));
    const draftProfile = parse(body.content);
    expect(body).toMatchObject({ entity_type: "research_profile", entity_id: "3d-gaussian-splatting" });
    expect(draftProfile).toMatchObject({
      id: "3d-gaussian-splatting",
      title: "3D Gaussian Splatting",
      description: "New view synthesis work.",
      lenses: [{ id: "main", title: "Main focus", queries: ["continual learning regularization"] }],
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
    fireEvent.change(screen.getByLabelText("New Profile title"), { target: { value: "Resumed Profile" } });
    fireEvent.change(screen.getByLabelText("Initial Query"), { target: { value: "continual learning" } });
    fireEvent.click(screen.getByRole("button", { name: "Create Research Profile" }));

    expect(await screen.findByText("Existing unpublished Profile Draft resumed. Closing this editor will keep the Draft.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "关闭" }));

    await waitFor(() => expect(screen.queryByRole("dialog", { name: "编辑 Resumed Profile" })).toBeNull());
    expect(mockFetch.mock.calls.some(([input, init]) => String(input) === "/api/drafts/profile-draft-1" && init?.method === "DELETE")).toBe(false);
    expect(researchProfileDraft).not.toBeNull();
  });

  it("adds a numeric suffix when a generated Profile ID is already used", () => {
    render(<ResearchProfileCreateDialog
      profiles={[profileSummary, { ...profileSummary, id: "continual-learning-2" }]}
      sourceProfile={null}
      onClose={() => undefined}
      onCreated={() => undefined}
    />);
    fireEvent.change(screen.getByLabelText("New Profile title"), { target: { value: "Continual Learning" } });
    fireEvent.click(screen.getByText("Advanced identifiers"));
    expect((screen.getByLabelText("New Profile ID") as HTMLInputElement).value).toBe("continual-learning-3");
  });

  it("duplicates a Profile's canonical settings into a new Draft", async () => {
    const created = vi.fn();
    render(<ResearchProfileCreateDialog profiles={[profileSummary]} sourceProfile={profile as unknown as ResearchProfile} onClose={() => undefined} onCreated={created} />);
    expect(screen.queryByLabelText("Initial Lens ID")).toBeNull();
    expect(screen.queryByLabelText("Initial Query")).toBeNull();
    expect(screen.queryByLabelText("New Profile schedule")).toBeNull();
    fireEvent.change(screen.getByLabelText("New Profile ID"), { target: { value: "continual-learning-copy" } });
    fireEvent.change(screen.getByLabelText("New Profile title"), { target: { value: "Continual Learning Copy" } });
    fireEvent.click(screen.getByRole("button", { name: "Create Research Profile" }));

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

  it("automatically adds a unique copy suffix when duplicating an existing Profile", async () => {
    const created = vi.fn();
    render(<ResearchProfileCreateDialog
      profiles={[profileSummary, { ...profileSummary, id: "continual-learning-copy" }]}
      sourceProfile={profile as unknown as ResearchProfile}
      onClose={() => undefined}
      onCreated={created}
    />);

    expect((screen.getByLabelText("New Profile ID") as HTMLInputElement).value).toBe("continual-learning-copy-2");
    fireEvent.click(screen.getByRole("button", { name: "Create Research Profile" }));
    await waitFor(() => expect(created).toHaveBeenCalledTimes(1));
    const call = mockFetch.mock.calls.find(([input, init]) => String(input) === "/api/drafts" && init?.method === "POST");
    expect(JSON.parse(String(call?.[1]?.body))).toMatchObject({ entity_id: "continual-learning-copy-2" });
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

    expect(await screen.findByText("搜索已加入队列。")).toBeTruthy();
    const call = mockFetch.mock.calls.find(([input, init]) => String(input) === "/api/research/profiles/continual-learning/runs" && init?.method === "POST");
    expect(call).toBeTruthy();
    expect(JSON.parse(String(call?.[1]?.body))).toMatchObject({
      date_range: { mode: "custom", start: expectedStart, end: expectedEnd },
    });
  });

  it("automatically assigns extra queries to the highest-priority selected Lens", async () => {
    responseProfileDetail = {
      ...profileDetail,
      profile: {
        ...profile,
        lenses: [...profile.lenses, { id: "replay", title: "Replay", enabled: true, priority: "medium", queries: ["experience replay"], include_terms: ["replay"], exclude_terms: [] }],
      },
    };
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Search Now" }));
    fireEvent.change(screen.getByLabelText(/额外检索词/), { target: { value: "replay distillation" } });
    fireEvent.click(screen.getByText("高级搜索选项"));

    expect(screen.getByLabelText("额外检索词应用到")).toBeTruthy();
    fireEvent.click(screen.getByLabelText("从上次自动检索进度继续"));
    expect(screen.getByText("从自动检索尚未覆盖的位置继续查到现在。这次手动搜索不会改变自动检索的进度。")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "加入搜索队列" }));
    expect(await screen.findByText("搜索已加入队列。")).toBeTruthy();
    const call = mockFetch.mock.calls.find(([input, init]) => String(input) === "/api/research/profiles/continual-learning/runs" && init?.method === "POST");
    expect(JSON.parse(String(call?.[1]?.body))).toMatchObject({
      lenses: ["regularization", "replay"],
      date_range: { mode: "incremental" },
      additional_queries: ["replay distillation"],
      additional_query_lens: "regularization",
    });
  });

  it("keeps discovery active when DeepSeek analysis is disabled", async () => {
    responseProfileDetail = {
      ...profileDetail,
      profile: {
        ...profile,
        ai_analysis: { ...profile.ai_analysis, enabled: false },
      },
    };
    render(<App />);

    expect(await screen.findByText(
      "AI 分析已关闭。系统仍会收集论文，但不会向 DeepSeek 发送论文或知识库内容，也不会生成推荐候选。重新开启后，系统会逐步处理之前收集但尚未分析的论文。",
    )).toBeTruthy();
    expect(screen.getByRole("button", { name: "Search Now" }).hasAttribute("disabled")).toBe(false);
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
      "No active default Focus · 自动发现当前不会执行",
    )).toBeTruthy();
    expect(screen.getByText("Search Now 仍可临时选择 Research Focus。")).toBeTruthy();
    const searchButton = screen.getByRole("button", { name: "Search Now" });
    expect(searchButton.hasAttribute("disabled")).toBe(false);
    fireEvent.click(searchButton);

    const searchForm = screen.getByRole("heading", { name: "Research Focus" }).closest("form");
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

  it("keeps manual search available while automatic research is paused", async () => {
    responseProfileDetail = {
      ...profileDetail,
      runtime_state: {
        ...profileDetail.runtime_state!,
        paused_until: new Date(Date.now() + 86_400_000).toISOString(),
      },
    };
    render(<App />);

    expect(await screen.findByText(/自动检索已暂停至 .*。手动搜索仍可使用。/)).toBeTruthy();
    const searchButton = screen.getByRole("button", { name: "Search Now" });
    expect(searchButton.hasAttribute("disabled")).toBe(false);
    fireEvent.click(searchButton);
    fireEvent.click(screen.getByRole("button", { name: "加入搜索队列" }));
    expect(await screen.findByText("搜索已加入队列。")).toBeTruthy();
  });

  it("explains both resume policies and keeps advanced catch-up settings inline", () => {
    render(<ResearchProfilePanel
      summary={profileSummary}
      detail={{
        ...profileDetail,
        runtime_state: { ...profileDetail.runtime_state!, paused_until: new Date(Date.now() + 86_400_000).toISOString() },
      }}
      onRefresh={() => undefined}
      onQueued={() => undefined}
      onEditDefaults={() => undefined}
    />);

    expect(screen.getByRole("heading", { name: "恢复 Research" })).toBeTruthy();
    expect(screen.getByText(/从暂停前尚未完成的 scheduled watermark 继续搜索/)).toBeTruthy();
    const advanced = screen.getByText("高级选项").closest("details") as HTMLDetailsElement;
    expect(advanced.open).toBe(false);
    fireEvent.click(screen.getByText("高级选项"));
    expect(advanced.open).toBe(true);
    expect(screen.getByLabelText("自定义追赶天数")).toBeTruthy();

    fireEvent.change(screen.getByLabelText("恢复方式"), { target: { value: "from_now" } });
    expect(screen.getByText("把 scheduled watermark 推进到现在，跳过暂停期间遗漏的时间窗，只搜索现在之后的新内容。")).toBeTruthy();
    expect(screen.queryByText("高级选项")).toBeNull();
  });

  it("keeps Resume in the strategy panel and sends the selected from-now policy", async () => {
    render(<ResearchProfilePanel
      summary={profileSummary}
      detail={{
        ...profileDetail,
        runtime_state: { ...profileDetail.runtime_state!, paused_until: new Date(Date.now() + 86_400_000).toISOString() },
      }}
      onRefresh={() => undefined}
      onQueued={() => undefined}
      onEditDefaults={() => undefined}
    />);

    expect(screen.queryByRole("button", { name: "Resume", exact: true })).toBeNull();
    expect(screen.getAllByRole("button", { name: "Resume Research" })).toHaveLength(1);
    const resumeButton = screen.getByRole("button", { name: "Resume Research" });
    fireEvent.click(resumeButton);
    await waitFor(() => expect(mockFetch.mock.calls.filter(([input, init]) => String(input) === "/api/research/profiles/continual-learning/resume" && init?.method === "POST")).toHaveLength(1));
    const catchUpCall = mockFetch.mock.calls.find(([input, init]) => String(input) === "/api/research/profiles/continual-learning/resume" && init?.method === "POST");
    expect(JSON.parse(String(catchUpCall?.[1]?.body))).toEqual({ strategy: "catch_up" });
    await waitFor(() => expect(resumeButton.hasAttribute("disabled")).toBe(false));

    fireEvent.change(screen.getByLabelText("恢复方式"), { target: { value: "from_now" } });
    fireEvent.click(resumeButton);

    await waitFor(() => expect(mockFetch.mock.calls.filter(([input, init]) => String(input) === "/api/research/profiles/continual-learning/resume" && init?.method === "POST")).toHaveLength(2));
    const fromNowCall = mockFetch.mock.calls.filter(([input, init]) => String(input) === "/api/research/profiles/continual-learning/resume" && init?.method === "POST")[1];
    expect(JSON.parse(String(fromNowCall?.[1]?.body))).toEqual({ strategy: "from_now" });
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
    fireEvent.click(screen.getByRole("button", { name: "Pause automatic research" }));

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
    expect(screen.getByLabelText("Enable unattended DeepSeek analysis")).toBeTruthy();
    expect(screen.getByText(/AI 分析已开启/)).toBeTruthy();
    expect(screen.getByText(/论文标题、作者、摘要和所选或检索到的相关知识片段会发送给 DeepSeek/)).toBeTruthy();
    expect(screen.getByText(/筛选规则和搜索默认值的修改只影响后续 Research Run/)).toBeTruthy();
    fireEvent.click(screen.getByText("高级设置"));
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
    fireEvent.change(screen.getByLabelText("New Research Focus name"), { target: { value: "Regularization" } });
    fireEvent.change(screen.getByLabelText("Initial search query"), { target: { value: "replay continual learning" } });
    fireEvent.click(screen.getByRole("button", { name: "+ Add Research Focus" }));
    const originalLens = screen.getByLabelText("Focus regularization name").closest("article");
    fireEvent.click(within(originalLens as HTMLElement).getByText("高级筛选与标识"));
    fireEvent.click(within(originalLens as HTMLElement).getByRole("button", { name: "Remove Research Focus regularization" }));
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
    expect(draftContent).toContain("id: regularization-2");
    expect(draftContent).toContain("title: Regularization");
    expect(parse(draftContent).lenses.map((lens: { id: string }) => lens.id)).toEqual(["regularization-2"]);
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

  it("keeps advanced defaults collapsed and rejects empty numeric edits without saving them", async () => {
    render(<ResearchProfileDefaultsEditor
      profile={profile as unknown as ResearchProfile}
      canonicalContent={stringify(profile, { lineWidth: 0 })}
      draftCreatedInThisFlow={false}
      onClose={() => undefined}
      onPublished={() => undefined}
    />);
    expect(await screen.findByRole("heading", { name: "编辑 Continual Learning" })).toBeTruthy();
    expect((screen.getByText("高级设置").closest("details") as HTMLDetailsElement).open).toBe(false);

    const inboxLimit = screen.getByRole("spinbutton", { name: "Inbox max new candidates" });
    fireEvent.change(inboxLimit, { target: { value: "" } });
    fireEvent.blur(inboxLimit);

    expect((await screen.findByRole("alert")).textContent).toContain("Enter a whole number greater than or equal to 0.");
    expect(mockFetch.mock.calls.some(([input, init]) => String(input) === "/api/drafts" && init?.method === "POST")).toBe(false);
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

  it("publishes a re-enabled Profile without a general catch-up review", async () => {
    responseProfileDetail = {
      ...profileDetail,
      profile: { ...profile, enabled: false },
      canonical_content: stringify({ ...profile, enabled: false }, { lineWidth: 0 }),
    };
    responseProfileSummary = { ...profileSummary, enabled: false };
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Edit Defaults" }));
    fireEvent.click(await screen.findByLabelText("Enable Research Profile"));
    fireEvent.click(screen.getByRole("button", { name: "Review Diff" }));

    const publishButton = await screen.findByRole("button", { name: "Publish Defaults" });
    expect(publishButton.hasAttribute("disabled")).toBe(false);
    fireEvent.click(publishButton);

    await waitFor(() => {
      const call = mockFetch.mock.calls.find(([input, init]) => String(input) === "/api/publish" && init?.method === "POST");
      expect(JSON.parse(String(call?.[1]?.body))).toEqual({
        draft_id: "profile-draft-1",
        expected_revision: 1,
      });
    });
  });

  it("opens Save Source from candidate details in the Unified Workspace", async () => {
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: /Why this candidate/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Save Source" }));

    expect(await screen.findByText("Source Metadata Editor")).toBeTruthy();
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
  summary: "A new parameter importance estimation method for continual learning.", why_relevant: "It matches the regularization Lens and studies parameter importance.", reading_reason: "Compare its adaptive estimates against EWC.",
  summary_zh: "这篇论文提出一种新的持续学习参数重要性估计方法。", why_relevant_zh: "它与正则化方向相关，并研究参数重要性。", reading_reason_zh: "将其自适应估计结果与 EWC 进行比较。",
  readiness: "medium", known_prerequisites: ["Fisher information"], missing_prerequisites: ["Online curvature estimation"], why_now: "It connects a known foundation to the current gap.", term_candidates: [],
  existing_relations: [{ entity_type: "term", entity_id: "fisher-information", relation: "extends", reason: "Uses Fisher information to estimate parameter importance.", reason_zh: "使用 Fisher 信息估计参数重要性。" }],
  suggested_collection: "continual-learning", suggested_section: "Regularization",
};

const candidateListItem = { candidate, work, analysis, recommended_score: 0.84, discovered_term_candidate_count: 2 };
const candidateDetail = {
  candidate: { ...candidate, first_viewed_at: "2026-10-03T00:00:00+00:00", last_viewed_at: "2026-10-03T00:00:00+00:00" },
  work,
  recommended_score: 0.84,
  discovered_term_candidate_count: 2,
  analysis: { id: "analysis-1", work_id: work.id, profile_id: profile.id, input_hash: "sha256:abc", outcome: "surface", analysis, provider: "deepseek", model: "deepseek-chat", prompt_version: "research-candidate-analysis-v1", analysis_version: 1, context_entity_ids: ["gem-sgd"], input_context: { analysis_version: 1, prompt_version: "research-candidate-analysis-v1", provider: "deepseek", model: "deepseek-chat", work: { ...work }, profile: { id: profile.id, title: profile.title, description: profile.description, breadth: "balanced", breadth_policy: "Include work related to the core topic and adjacent methods." }, matched_lens: { ...profile.lenses[0] }, knowledge_context: { focus_query: "fisher information catastrophic forgetting", budget: 5, omitted_count: 0, cards: [{ entity_type: "document", entity_id: "gem-sgd", title: "Elastic Weight Consolidation", review_status: "reviewed", topics: ["continual-learning"], domains: [], relevant_sections: [{ heading: "Method", excerpt: "Snapshot excerpt used at analysis time." }], metadata: {}, pinned: true, retrieval_score: 0.9 }] } }, analyzed_at: "2026-10-03T00:00:00+00:00" },
  conversion_blocker: null,
  source_match_candidates: [],
  discoveries: [{ id: "discovery-1", work_id: work.id, profile_id: profile.id, lens_id: "regularization", provider: "arxiv", provider_record_id: "2501.00001", query_key: "query-key", query_text: "fisher information catastrophic forgetting", metadata: {}, discovered_at: "2026-10-03T00:00:00+00:00" }],
  knowledge_relations: analysis.existing_relations,
  linked_entities: [{ entity_type: "source", entity_id: "published-paper", relation_type: "source", created_at: "2026-10-03T00:00:00+00:00" }],
  pending_links: [],
};
