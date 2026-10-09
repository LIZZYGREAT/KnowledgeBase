import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { WorkspacePage } from "../../src/Workspace";
import { WorkspaceMetadataDrawer } from "../../src/workspace/WorkspaceMetadataDrawer";
import type { Draft, EntityDetail, PresentationAnnotation, Proposal } from "../../src/api";
import { navigateWithGuards, type NavigationGuard, type RegisterBeforeNavigate } from "../../src/navigation";

const api = vi.hoisted(() => ({
  getEntity: vi.fn(),
  getCollectionNavigation: vi.fn(),
  listDrafts: vi.fn(),
  getDraft: vi.fn(),
  createDraft: vi.fn(),
  updateDraft: vi.fn(),
  discardDraft: vi.fn(),
  compareDraft: vi.fn(),
  preflightDraft: vi.fn(),
  preflightDraftsBatch: vi.fn(),
  publishDraft: vi.fn(),
  publishDraftsBatch: vi.fn(),
  listProposals: vi.fn(),
  listAllEntities: vi.fn(),
  recordDocumentOpen: vi.fn(),
  listPresentationAnnotations: vi.fn(),
  createPresentationAnnotation: vi.fn(),
  deletePresentationAnnotation: vi.fn(),
  requestAIProposal: vi.fn(),
  applyProposalToDraft: vi.fn(),
  rejectProposal: vi.fn(),
}));

vi.mock("../../src/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../src/api")>()),
  ...api,
}));

vi.mock("../../src/Explorer", () => ({ ExplorerPage: () => null }));

const canonicalBody = "# Main heading\n\nA paragraph with a selected phrase.";
const canonicalContent = [
  "---",
  "title: Quick Start",
  "type: learning-note",
  "review:",
  "  human:",
  "    status: approved",
  "maintenance:",
  "  status: current",
  "sources: []",
  "external_artifacts: []",
  "---",
  canonicalBody,
].join("\n");

let drafts: Draft[];
let proposals: Proposal[];
let annotations: PresentationAnnotation[];
let draftSequence: number;
let conflictOnPreflight: boolean;
let publishedEntity: EntityDetail | null;
let publishedSource: EntityDetail | null;

function makeEntity(id = "quick-start"): EntityDetail {
  const titles: Record<string, string> = {
    "second-note": "Second Note",
    "formatted-note": "Formatted Note",
    "linked-note": "Linked Note",
    "repeated-note": "Repeated Note",
  };
  const bodies: Record<string, string> = {
    "second-note": "# Second heading\n\nSecond entity content.",
    "formatted-note": "# Main heading\n\nA **very important** result.",
    "linked-note": "# Main heading\n\nRead [the linked page](https://example.com) carefully.",
    "repeated-note": "# Main heading\n\nsame text and same text.",
  };
  const title = titles[id] ?? "Quick Start";
  const body = bodies[id] ?? canonicalBody;
  const canonical = canonicalContent
    .replace("title: Quick Start", `title: ${title}`)
    .replace(canonicalBody, body);
  return {
    id,
    title,
    entity_type: "document",
    metadata: {
      type: "learning-note",
      review: { human: { status: "approved" } },
      maintenance: { status: "current" },
      sources: [],
      external_artifacts: [],
    },
    content: body,
    canonical_content: canonical,
    related_terms: [],
    backlinks: [],
    detected_mentions: [],
    evidence: [],
    related_documents: [],
  };
}

function makeDraft(entityType: Draft["entity_type"], entityId: string, content: string): Draft {
  draftSequence += 1;
  return {
    id: `draft-${draftSequence}`,
    entity_type: entityType,
    entity_id: entityId,
    base_git_revision: "base-revision",
    base_content_hash: "base-hash",
    content,
    revision: 1,
    created_at: "2026-10-02T00:00:00Z",
    updated_at: "2026-10-02T00:00:00Z",
  };
}

function seedDraft(content = canonicalContent) {
  const draft = makeDraft("document", "quick-start", content);
  drafts.push(draft);
  return draft;
}

function installApiBehavior() {
  api.getEntity.mockImplementation(async (type: string, id: string) => {
    if (type === "source" && publishedSource?.id === id) return publishedSource;
    if (type === "document" && ["quick-start", "second-note", "formatted-note", "linked-note", "repeated-note"].includes(id)) {
      return publishedEntity?.id === id ? publishedEntity : makeEntity(id);
    }
    throw Object.assign(new Error("Not found"), { status: 404 });
  });
  api.getCollectionNavigation.mockResolvedValue(null);
  api.listDrafts.mockImplementation(async (type: string, id: string) => drafts.filter((draft) => draft.entity_type === type && draft.entity_id === id));
  api.getDraft.mockImplementation(async (id: string) => {
    const draft = drafts.find((item) => item.id === id);
    if (!draft) throw Object.assign(new Error("Draft not found"), { status: 404 });
    return { ...draft };
  });
  api.createDraft.mockImplementation(async (type: Draft["entity_type"], id: string, content: string) => {
    const draft = makeDraft(type, id, content);
    drafts.push(draft);
    return { draft, created: true };
  });
  api.updateDraft.mockImplementation(async (id: string, content: string, revision: number) => {
    const draft = drafts.find((item) => item.id === id);
    if (!draft) throw new Error("Draft not found");
    Object.assign(draft, { content, revision: revision + 1 });
    return { ...draft };
  });
  api.discardDraft.mockImplementation(async (id: string) => {
    drafts = drafts.filter((draft) => draft.id !== id);
  });
  api.compareDraft.mockImplementation(async (id: string) => {
    const draft = drafts.find((item) => item.id === id);
    if (!draft) throw new Error("Draft not found");
    return {
      draft: { ...draft },
      base_content: canonicalContent,
      current_content: canonicalContent,
      current_git_revision: "current-revision",
      current_content_hash: conflictOnPreflight ? "changed-hash" : "base-hash",
      canonical_changed: conflictOnPreflight,
    };
  });
  api.preflightDraft.mockImplementation(async (id: string) => ({
    draft_id: id,
    valid: !conflictOnPreflight,
    conflict: conflictOnPreflight,
    errors: conflictOnPreflight ? ["Canonical changed"] : [],
    warnings: [],
  }));
  api.preflightDraftsBatch.mockImplementation(async (expectations: Array<{ draft_id: string }>) => ({
    results: expectations.map(({ draft_id }) => ({
      draft_id,
      valid: !conflictOnPreflight,
      conflict: conflictOnPreflight,
      errors: conflictOnPreflight ? ["Canonical changed"] : [],
      warnings: [],
    })),
  }));
  api.publishDraft.mockImplementation(async (id: string, _expectedRevision: number) => ({
    draft_id: id,
    entity_type: "document",
    entity_id: "quick-start",
    commit_revision: "publish-revision",
    warnings: [],
  }));
  api.publishDraftsBatch.mockResolvedValue({ results: [], commit_revision: "batch-revision", warnings: [] });
  api.listProposals.mockImplementation(async () => proposals);
  api.listAllEntities.mockResolvedValue([]);
  api.recordDocumentOpen.mockResolvedValue(undefined);
  api.listPresentationAnnotations.mockImplementation(async () => annotations);
  api.createPresentationAnnotation.mockImplementation(async (payload: Omit<PresentationAnnotation, "id" | "created_at" | "updated_at">) => {
    const annotation: PresentationAnnotation = {
      ...payload,
      id: `annotation-${annotations.length + 1}`,
      created_at: "2026-10-02T00:00:00Z",
      updated_at: "2026-10-02T00:00:00Z",
    };
    annotations = [...annotations, annotation];
    return annotation;
  });
  api.deletePresentationAnnotation.mockResolvedValue(undefined);
  api.requestAIProposal.mockImplementation(async () => {
    const proposal: Proposal = {
      id: "proposal-selection",
      target_type: "document",
      target_id: "quick-start",
      kind: "selection-review",
      status: "proposed",
      base_content_hash: "draft-hash",
      payload: { selection: "A paragraph with a selected phrase." },
      diff_text: null,
      created_by: "human",
      provider: "DeepSeek",
      model: "mock",
      created_at: "2026-10-02T00:00:00Z",
      reviewed_at: null,
      review_note: null,
    };
    proposals = [...proposals, proposal];
    return { proposal, external_provider_notice: "Selection sent for review." };
  });
  api.applyProposalToDraft.mockImplementation(async (proposalId: string, draftId: string, revision: number) => {
    const draft = drafts.find((item) => item.id === draftId);
    if (!draft) throw new Error("Draft not found");
    if (draft.revision !== revision) throw Object.assign(new Error("Draft revision conflict"), { status: 409 });
    const proposal = proposals.find((item) => item.id === proposalId);
    if (!proposal) throw new Error("Proposal not found");
    const content = proposal.payload.content;
    if (typeof content !== "string") throw new Error("Proposal has no content candidate");
    Object.assign(draft, { content, revision: revision + 1 });
    const applied = {
      ...proposal,
      status: "drafted",
      payload: { ...proposal.payload, applied_content_hash: "candidate-hash" },
    };
    proposals = proposals.map((item) => item.id === proposalId ? applied : item);
    return { draft: { ...draft }, proposal: applied };
  });
  api.rejectProposal.mockImplementation(async (proposalId: string) => {
    const updated = proposals.find((item) => item.id === proposalId);
    if (!updated) throw new Error("Proposal not found");
    const rejected = { ...updated, status: "rejected" };
    proposals = proposals.map((item) => item.id === proposalId ? rejected : item);
    return rejected;
  });
}

function renderWorkspace(
  id = "quick-start",
  navigate: (path: string) => void = () => undefined,
  registerBeforeNavigate?: RegisterBeforeNavigate,
  batchCollectionId?: string,
  additionalDraftIds: string[] = [],
  researchGroupId?: string,
) {
  return render(<WorkspacePage type="document" id={id} navigate={navigate} registerBeforeNavigate={registerBeforeNavigate} batchCollectionId={batchCollectionId} additionalDraftIds={additionalDraftIds} researchGroupId={researchGroupId} />);
}

function renderSourceWorkspace(id: string) {
  return render(<WorkspacePage type="source" id={id} navigate={vi.fn()} />);
}

function renderGuardedWorkspace() {
  const guards = new Set<NavigationGuard>();
  const navigate = vi.fn();
  const registerBeforeNavigate: RegisterBeforeNavigate = (guard) => {
    guards.add(guard);
    return () => { guards.delete(guard); };
  };
  const requestNavigation = (path: string) => navigateWithGuards(path, guards, navigate);
  const view = renderWorkspace("quick-start", (path) => { void requestNavigation(path); }, registerBeforeNavigate);
  return { ...view, guards, navigate, requestNavigation };
}

function EntitySwitchHarness() {
  const [id, setId] = useState("quick-start");
  return <>
    <button type="button" onClick={() => setId("second-note")}>切换实体</button>
    <WorkspacePage type="document" id={id} navigate={vi.fn()} />
  </>;
}

function selectParagraph(container: HTMLElement) {
  const paragraph = container.querySelector(".reader-markdown-wrap p");
  if (!paragraph?.firstChild || paragraph.firstChild.nodeType !== Node.TEXT_NODE) throw new Error("Reader paragraph text was not rendered.");
  const text = paragraph.firstChild as Text;
  const range = document.createRange();
  range.setStart(text, 0);
  range.setEnd(text, text.length);
  Object.defineProperty(range, "getBoundingClientRect", {
    configurable: true,
    value: () => ({ top: 20, right: 320, bottom: 40, left: 30, width: 290, height: 20, x: 30, y: 20, toJSON: () => ({}) }),
  });
  const selection = window.getSelection();
  selection?.removeAllRanges();
  selection?.addRange(range);
  fireEvent.mouseUp(container.querySelector(".reader-markdown-wrap")!);
}

function selectWholeParagraph(container: HTMLElement) {
  const paragraph = container.querySelector(".reader-markdown-wrap p");
  if (!paragraph) throw new Error("Reader paragraph was not rendered.");
  const walker = document.createTreeWalker(paragraph, NodeFilter.SHOW_TEXT);
  const textNodes: Text[] = [];
  while (walker.nextNode()) textNodes.push(walker.currentNode as Text);
  if (!textNodes.length) throw new Error("Reader paragraph text was not rendered.");
  const range = document.createRange();
  range.setStart(textNodes[0], 0);
  range.setEnd(textNodes.at(-1)!, textNodes.at(-1)!.length);
  Object.defineProperty(range, "getBoundingClientRect", {
    configurable: true,
    value: () => ({ top: 20, right: 320, bottom: 40, left: 30, width: 290, height: 20, x: 30, y: 20, toJSON: () => ({}) }),
  });
  const selection = window.getSelection();
  selection?.removeAllRanges();
  selection?.addRange(range);
  fireEvent.mouseUp(container.querySelector(".reader-markdown-wrap")!);
}

function selectParagraphSubstring(container: HTMLElement, selectedText: string) {
  const paragraph = container.querySelector(".reader-markdown-wrap p");
  if (!(paragraph?.firstChild instanceof Text)) throw new Error("Reader paragraph text was not rendered.");
  const text = paragraph.firstChild;
  const start = text.data.indexOf(selectedText);
  if (start < 0) throw new Error("Selected text was not found in the paragraph.");
  const range = document.createRange();
  range.setStart(text, start);
  range.setEnd(text, start + selectedText.length);
  Object.defineProperty(range, "getBoundingClientRect", {
    configurable: true,
    value: () => ({ top: 20, right: 320, bottom: 40, left: 30, width: 290, height: 20, x: 30, y: 20, toJSON: () => ({}) }),
  });
  const selection = window.getSelection();
  selection?.removeAllRanges();
  selection?.addRange(range);
  fireEvent.mouseUp(container.querySelector(".reader-markdown-wrap")!);
}

function selectAcrossReaderBlocks(container: HTMLElement) {
  const root = container.querySelector(".reader-markdown-wrap");
  const heading = root?.querySelector("h1");
  const paragraph = root?.querySelector("p");
  if (!root || !heading?.firstChild || !paragraph?.firstChild) throw new Error("Reader blocks were not rendered.");
  const endText = paragraph.firstChild as Text;
  const range = document.createRange();
  range.setStart(heading.firstChild, 0);
  range.setEnd(endText, endText.length);
  Object.defineProperty(range, "getBoundingClientRect", {
    configurable: true,
    value: () => ({ top: 20, right: 320, bottom: 40, left: 30, width: 290, height: 20, x: 30, y: 20, toJSON: () => ({}) }),
  });
  const selection = window.getSelection();
  selection?.removeAllRanges();
  selection?.addRange(range);
  fireEvent.mouseUp(root);
}

describe("Workspace React integration", () => {
  beforeEach(() => {
    drafts = [];
    proposals = [];
    annotations = [];
    draftSequence = 0;
    conflictOnPreflight = false;
    publishedEntity = null;
    publishedSource = null;
    vi.clearAllMocks();
    installApiBehavior();
  });

  it("keeps incomplete Source year and URL text local while syncing valid values immediately", () => {
    const onFrontmatterUpdate = vi.fn();
    render(<WorkspaceMetadataDrawer
      type="source"
      id="ewc-2017"
      content={["schema_version: 1", "id: ewc-2017", "type: paper", "title: Elastic Weight Consolidation", "year: 2017", "url: https://example.org/paper", "identifiers: {}", "attachments: {}"].join("\n")}
      sourceEntries={[]}
      sourceError=""
      canonicalEvidenceCount={0}
      onFrontmatterUpdate={onFrontmatterUpdate}
      onFrontmatterListUpdate={vi.fn()}
      onSourcePdfChange={vi.fn()}
      onNavigate={vi.fn()}
      onClose={vi.fn()}
      onError={vi.fn()}
    />);

    const year = screen.getByLabelText("Year");
    for (const value of ["2", "20", "202", "999"]) {
      fireEvent.change(year, { target: { value } });
      fireEvent.blur(year);
      expect(onFrontmatterUpdate).not.toHaveBeenCalledWith("year", expect.anything());
    }
    expect(screen.getByText("年份须为空，或为 1000 到 9999 之间的整数。")).toBeTruthy();

    fireEvent.change(year, { target: { value: "2026" } });
    expect(onFrontmatterUpdate).toHaveBeenCalledWith("year", 2026);
    fireEvent.change(year, { target: { value: "" } });
    expect(onFrontmatterUpdate).toHaveBeenCalledWith("year", null);

    const url = screen.getByLabelText("URL");
    fireEvent.change(url, { target: { value: "ftp://example.org/paper" } });
    fireEvent.blur(url);
    expect(onFrontmatterUpdate).not.toHaveBeenCalledWith("url", expect.anything());
    expect(screen.getByText("URL 须为空，或使用有效的 http:// / https:// 地址。")).toBeTruthy();
    fireEvent.change(url, { target: { value: "http:example.org/paper" } });
    fireEvent.blur(url);
    expect(onFrontmatterUpdate).not.toHaveBeenCalledWith("url", expect.anything());

    fireEvent.change(url, { target: { value: "http://example.org/paper" } });
    expect(onFrontmatterUpdate).toHaveBeenCalledWith("url", "http://example.org/paper");
    fireEvent.change(url, { target: { value: "" } });
    expect(onFrontmatterUpdate).toHaveBeenCalledWith("url", null);
  });

  it("shows Source autosave failures in the open metadata drawer and hands them back to the reader on close", async () => {
    const user = userEvent.setup();
    const id = "ewc-2017";
    const content = [
      "schema_version: 1",
      `id: ${id}`,
      "type: paper",
      "title: Elastic Weight Consolidation",
      "authors: []",
      "year: 2017",
      "identifiers: {}",
      "url: https://example.org/paper",
      "attachments: {}",
    ].join("\n");
    publishedSource = {
      id,
      title: "Elastic Weight Consolidation",
      entity_type: "source",
      metadata: { type: "paper", authors: [], year: 2017, identifiers: {}, url: "https://example.org/paper", attachments: {} },
      content: null,
      canonical_content: content,
      related_terms: [],
      backlinks: [],
      detected_mentions: [],
      evidence: [],
      related_documents: [],
    };
    drafts.push(makeDraft("source", id, content));
    api.updateDraft.mockRejectedValueOnce(new Error("runtime write failed"));
    renderSourceWorkspace(id);

    await screen.findByRole("heading", { name: "Elastic Weight Consolidation" });
    await user.click(screen.getByRole("button", { name: "元数据" }));
    const title = screen.getByLabelText("标题");
    await user.clear(title);
    await user.type(title, "Updated title");

    const metadataDrawer = screen.getByRole("dialog", { name: "元数据" });
    await waitFor(() => {
      expect(metadataDrawer.querySelector('[role="alert"]')?.textContent).toContain("runtime write failed");
      expect(document.querySelector(".workspace-reader-save-error")).toBeNull();
    }, { timeout: 4000 });

    await user.click(screen.getByRole("button", { name: "关闭抽屉" }));
    await waitFor(() => expect(document.querySelector(".workspace-reader-save-error")?.textContent).toContain("保存失败：runtime write failed"), { timeout: 4000 });
  });

  it("keeps reading and inline editing in one Workspace, autosaves, then publishes through the review drawer", async () => {
    const user = userEvent.setup();
    const { container } = renderWorkspace();
    await screen.findByRole("heading", { name: "Quick Start" });
    expect(api.getEntity.mock.calls.filter(([type, id]) => type === "document" && id === "quick-start")).toHaveLength(1);

    await user.click(await screen.findByRole("button", { name: "编辑第 2 个区块" }));
    const editor = await screen.findByRole("textbox", { name: "Markdown 区块 2" });
    await user.clear(editor);
    await user.type(editor, "Revised paragraph.");
    expect((editor as HTMLTextAreaElement).value).toBe("Revised paragraph.");
    await user.click(screen.getByRole("button", { name: "完成区块" }));
    await waitFor(() => expect(drafts[0]?.content).toContain("Revised paragraph."), { timeout: 2500 });

    await user.click(screen.getByRole("button", { name: "Source" }));
    await screen.findByRole("heading", { name: "完整源码" });
    expect(container.querySelector(".workspace-shell")).not.toBeNull();
    await user.click(screen.getByRole("button", { name: "完整源码" }));
    expect(screen.getByRole("textbox", { name: "Markdown 完整源码" })).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "关闭" }));
    await user.click(await screen.findByRole("button", { name: "发布" }));
    await screen.findByRole("heading", { name: "变更摘要" });
    const publishButton = await screen.findByRole("button", { name: "确认发布" });
    await waitFor(() => expect((publishButton as HTMLButtonElement).disabled).toBe(false));
    await user.click(publishButton);
    await waitFor(() => expect(api.publishDraft).toHaveBeenCalledOnce());
    expect(api.publishDraft).toHaveBeenCalledWith("draft-1", 1);
  });

  it("fetches the Reader entity once and retries canonical hydration through the Workspace owner", async () => {
    const user = userEvent.setup();
    const entity = makeEntity();
    api.getEntity.mockRejectedValueOnce(new Error("temporary read failure"))
      .mockResolvedValueOnce(entity);
    renderWorkspace();

    expect(await screen.findByText("temporary read failure")).toBeTruthy();
    expect(api.getEntity).toHaveBeenCalledTimes(1);
    await user.click(screen.getByRole("button", { name: "重试" }));
    await screen.findByRole("heading", { name: "Quick Start" });
    expect(api.getEntity).toHaveBeenCalledTimes(2);
  });

  it("flushes a dirty Draft before internal navigation", async () => {
    const user = userEvent.setup();
    const { navigate, requestNavigation } = renderGuardedWorkspace();
    await screen.findByRole("heading", { name: "Quick Start" });
    await user.click(await screen.findByRole("button", { name: "编辑第 2 个区块" }));
    const editor = await screen.findByRole("textbox", { name: "Markdown 区块 2" });
    fireEvent.change(editor, { target: { value: "Saved before leaving." } });

    let allowed = false;
    await act(async () => { allowed = await requestNavigation("/library"); });

    expect(allowed).toBe(true);
    expect(api.createDraft).toHaveBeenCalledWith("document", "quick-start", expect.stringContaining("Saved before leaving."));
    expect(navigate).toHaveBeenCalledWith("/library");
  });

  it("keeps the current page open when navigation saving fails", async () => {
    const user = userEvent.setup();
    const { navigate, requestNavigation } = renderGuardedWorkspace();
    await screen.findByRole("heading", { name: "Quick Start" });
    await user.click(await screen.findByRole("button", { name: "编辑第 2 个区块" }));
    const editor = await screen.findByRole("textbox", { name: "Markdown 区块 2" });
    fireEvent.change(editor, { target: { value: "Keep this page open." } });
    api.createDraft.mockRejectedValueOnce(new Error("network unavailable"));

    let allowed = true;
    await act(async () => { allowed = await requestNavigation("/library"); });

    expect(allowed).toBe(false);
    expect(navigate).not.toHaveBeenCalled();
    expect(screen.getByRole("alert").textContent).toContain("network unavailable");
  });

  it("keeps the current page open and shows Runtime conflict when navigation saving conflicts", async () => {
    const user = userEvent.setup();
    const { navigate, requestNavigation } = renderGuardedWorkspace();
    await screen.findByRole("heading", { name: "Quick Start" });
    await user.click(await screen.findByRole("button", { name: "编辑第 2 个区块" }));
    const editor = await screen.findByRole("textbox", { name: "Markdown 区块 2" });
    fireEvent.change(editor, { target: { value: "Keep this page open through conflict." } });
    api.createDraft.mockResolvedValueOnce({
      draft: makeDraft("document", "quick-start", "A different session's content."),
      created: false,
    });

    let allowed = true;
    await act(async () => { allowed = await requestNavigation("/library"); });

    expect(allowed).toBe(false);
    expect(navigate).not.toHaveBeenCalled();
    expect(screen.getByRole("heading", { name: "Draft 内容冲突" })).toBeTruthy();
    expect((screen.getByRole("button", { name: "丢弃 Draft" }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText("请等待保存完成或先处理冲突")).toBeTruthy();
  });

  it("disables Reader Discard while a save is in flight", async () => {
    const draft = seedDraft();
    let resolveUpdate!: (updated: Draft) => void;
    api.updateDraft.mockImplementationOnce(() => new Promise((resolve) => {
      resolveUpdate = resolve;
    }));
    renderWorkspace();
    await screen.findByRole("heading", { name: "Quick Start" });
    await userEvent.setup().click(await screen.findByRole("button", { name: "编辑第 2 个区块" }));
    fireEvent.change(await screen.findByRole("textbox", { name: "Markdown 区块 2" }), {
      target: { value: "Save in flight" },
    });
    await waitFor(() => expect(api.updateDraft).toHaveBeenCalledOnce(), { timeout: 2500 });

    expect((screen.getByRole("button", { name: "丢弃 Draft" }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText("请等待保存完成或先处理冲突")).toBeTruthy();

    await act(async () => {
      const content = api.updateDraft.mock.calls[0][1] as string;
      Object.assign(draft, { content, revision: draft.revision + 1 });
      resolveUpdate({ ...draft });
    });
    await waitFor(() => expect((screen.getByRole("button", { name: "丢弃 Draft" }) as HTMLButtonElement).disabled).toBe(false));
  });

  it("opens Metadata directly over the Reader", async () => {
    const user = userEvent.setup();
    renderWorkspace();
    await screen.findByRole("heading", { name: "Quick Start" });

    await user.click(screen.getByRole("button", { name: "元数据" }));

    await screen.findByRole("heading", { name: "元数据" });
    expect(screen.queryByRole("heading", { name: "编辑 quick-start" })).toBeNull();
  });

  it("opens the AI review drawer directly over the Reader", async () => {
    const user = userEvent.setup();
    renderWorkspace();
    await screen.findByRole("heading", { name: "Quick Start" });

    await user.click(screen.getByRole("button", { name: "AI 审阅" }));

    await screen.findByRole("heading", { name: "AI 辅助审阅" });
    expect(screen.queryByRole("heading", { name: "编辑 quick-start" })).toBeNull();
  });

  it("opens AI review for a new Term Draft and explains that its Proposal awaits Apply", async () => {
    const id = "stable-index";
    const content = [
      "---",
      "schema_version: 1",
      `id: ${id}`,
      "title: Stable Index",
      "type: concept",
      "depth: stub",
      "aliases: []",
      "domains: []",
      "topics: []",
      "tags: []",
      "sources: []",
      "---",
      "",
    ].join("\n");
    const draft = makeDraft("term", id, content);
    drafts.push(draft);
    proposals = [{
      id: "proposal-stable-index",
      target_type: "term",
      target_id: id,
      kind: "term_revision",
      status: "proposed",
      base_content_hash: "draft-hash",
      payload: { draft_id: draft.id, content: "# Stable Index\n\nA stable index retains canonical facts." },
      diff_text: "+A stable index retains canonical facts.",
      created_by: "ai",
      provider: "mock",
      model: "mock",
      created_at: "2026-10-02T00:00:00Z",
      reviewed_at: null,
      review_note: null,
    }];

    render(<WorkspacePage
      type="term"
      id={id}
      navigate={vi.fn()}
      openAIAssistOnLoad
      proposalGeneratedOnLoad
      termCandidateId="candidate-stable-index"
    />);

    await screen.findByRole("heading", { name: "AI 辅助审阅" });
    expect(await screen.findByText("已生成建议，等待 Apply to Draft。")).toBeTruthy();
    expect(screen.getByText("+A stable index retains canonical facts.")).toBeTruthy();
    expect(api.listProposals).toHaveBeenCalledWith(undefined, "term", id);

    await userEvent.click(screen.getByRole("button", { name: "Apply to Draft" }));
    await screen.findByText(/候选已写入 Draft/);
    expect(screen.queryByText("已生成建议，等待 Apply to Draft。")).toBeNull();

    await userEvent.click(screen.getByRole("checkbox", { name: /我同意/ }));
    await userEvent.click(screen.getByRole("button", { name: "Term Draft 建议" }));
    await waitFor(() => expect(api.requestAIProposal).toHaveBeenCalledWith(
      "term-draft", draft.id, undefined, "candidate-stable-index",
    ));
  });

  it("applies a content Proposal to the saved Draft and advances its revision", async () => {
    const user = userEvent.setup();
    const candidate = canonicalContent.replace("selected phrase", "AI candidate");
    api.requestAIProposal.mockImplementationOnce(async () => {
      const proposal: Proposal = {
        id: "proposal-content",
        target_type: "document",
        target_id: "quick-start",
        kind: "document_revision",
        status: "proposed",
        base_content_hash: "draft-hash",
        payload: { draft_id: "draft-1", content: candidate },
        diff_text: "candidate diff",
        created_by: "ai",
        provider: "mock",
        model: "mock",
        created_at: "2026-10-02T00:00:00Z",
        reviewed_at: null,
        review_note: null,
      };
      proposals = [proposal];
      return { proposal, external_provider_notice: "Candidate ready." };
    });
    renderWorkspace();
    await screen.findByRole("heading", { name: "Quick Start" });
    await user.click(screen.getByRole("button", { name: "AI 审阅" }));
    await user.click(screen.getByRole("checkbox", { name: /我同意/ }));
    await user.click(screen.getByRole("button", { name: "文档审阅" }));
    await screen.findByText("candidate diff");

    await user.click(screen.getByRole("button", { name: "Apply to Draft" }));

    await waitFor(() => expect(api.applyProposalToDraft).toHaveBeenCalledWith(
      "proposal-content", "draft-1", 1,
    ));
    expect(drafts[0].content).toBe(candidate);
    expect(drafts[0].revision).toBe(2);
    expect(screen.getByText(/候选已写入 Draft/)).toBeTruthy();
  });

  it("opens and confirms Publish Review directly from the Reader", async () => {
    const user = userEvent.setup();
    seedDraft(canonicalContent.replace("selected phrase", "reviewed from reader"));
    renderWorkspace();
    await screen.findByRole("heading", { name: "Quick Start" });

    await user.click(screen.getByRole("button", { name: "发布" }));
    await screen.findByRole("heading", { name: "变更摘要" });
    const publishButton = await screen.findByRole("button", { name: "确认发布" });
    await waitFor(() => expect((publishButton as HTMLButtonElement).disabled).toBe(false));
    await user.click(publishButton);

    await waitFor(() => expect(api.publishDraft).toHaveBeenCalledWith("draft-1", 1));
    expect(screen.queryByRole("heading", { name: "编辑 quick-start" })).toBeNull();
  });

  it("refreshes canonical Reader data after Publish and enables another publish after editing", async () => {
    const user = userEvent.setup();
    const publishedContent = canonicalContent
      .replace("title: Quick Start", "title: Published Title")
      .replace("sources: []", "sources:\n  - source-one")
      .replace("selected phrase", "published phrase");
    const publishedBody = canonicalBody.replace("selected phrase", "published phrase");
    const draft = seedDraft(publishedContent);
    annotations = [{
      id: "published-annotation",
      entity_type: "document",
      entity_id: "quick-start",
      style_type: "highlight",
      style_value: "yellow",
      selected_text: "published phrase",
      prefix_text: "A paragraph with a ",
      suffix_text: ".",
      start_offset: 0,
      end_offset: "published phrase".length,
      base_content_hash: "published-hash",
      status: "active",
      created_at: "2026-10-02T00:00:00Z",
      updated_at: "2026-10-02T00:00:00Z",
    }];
    api.publishDraft.mockImplementationOnce(async (id: string) => {
      const baseEntity = makeEntity();
      publishedEntity = {
        ...baseEntity,
        title: "Published Title",
        metadata: { ...baseEntity.metadata, sources: ["source-one"] },
        content: publishedBody,
        canonical_content: publishedContent,
      };
      publishedSource = {
        id: "source-one",
        title: "Updated Source",
        entity_type: "source",
        metadata: { type: "paper" },
        content: null,
        canonical_content: null,
        related_terms: [],
        backlinks: [],
        detected_mentions: [],
        evidence: [],
        related_documents: [],
      };
      return {
        draft_id: id,
        entity_type: "document",
        entity_id: "quick-start",
        commit_revision: "publish-revision",
        warnings: [],
      };
    });
    const { container } = renderWorkspace();
    await screen.findByRole("heading", { name: "Quick Start" });

    await user.click(await screen.findByRole("button", { name: "发布" }));
    await screen.findByRole("heading", { name: "变更摘要" });
    const publishButton = await screen.findByRole("button", { name: "确认发布" });
    await waitFor(() => expect((publishButton as HTMLButtonElement).disabled).toBe(false));
    await user.click(publishButton);

    await screen.findByRole("heading", { name: "Published Title" });
    await waitFor(() => expect(api.getEntity.mock.calls.filter(([type, id]) => type === "document" && id === "quick-start").length).toBe(2));
    await user.click(screen.getByRole("button", { name: "More" }));
    expect(await screen.findByRole("button", { name: /Updated Source/ })).toBeTruthy();

    selectParagraphSubstring(container, "published phrase");
    const annotationButton = await screen.findByRole("button", { name: "yellow 高亮" });
    await waitFor(() => expect((annotationButton as HTMLButtonElement).disabled).toBe(false));

    await user.click(await screen.findByRole("button", { name: "编辑第 2 个区块" }));
    await user.clear(await screen.findByRole("textbox", { name: "Markdown 区块 2" }));
    await user.type(screen.getByRole("textbox", { name: "Markdown 区块 2" }), "Edited after publishing.");
    await waitFor(() => expect((screen.getByRole("button", { name: "发布" }) as HTMLButtonElement).disabled).toBe(false));
    expect(draft.content).toBe(publishedContent);
  });

  it("preflights a new Document and its Collection reference as one batch", async () => {
    const user = userEvent.setup();
    const documentDraft = seedDraft(canonicalContent.replace("selected phrase", "batch reviewed"));
    const collectionDraft = makeDraft(
      "collection",
      "reading-list",
      "schema_version: 1\nid: reading-list\ntitle: Reading List\nstatus: active\nposition: 0\nnodes:\n  - id: quick-start\n    kind: entity\n    entity_type: document\n    entity_id: quick-start\n",
    );
    drafts.push(collectionDraft);
    renderWorkspace("quick-start", () => undefined, undefined, "reading-list");
    await screen.findByRole("heading", { name: "Quick Start" });

    await user.click(screen.getByRole("button", { name: "Publish All" }));

    await screen.findByRole("heading", { name: "变更摘要" });
    expect(api.preflightDraftsBatch).toHaveBeenCalledWith([
      { draft_id: documentDraft.id, expected_revision: documentDraft.revision },
      { draft_id: collectionDraft.id, expected_revision: collectionDraft.revision },
    ]);
    expect(api.preflightDraft).not.toHaveBeenCalled();
    await waitFor(() => expect((screen.getByRole("button", { name: /Publish All · 一个 Git 提交/ }) as HTMLButtonElement).disabled).toBe(false));
  });

  it("preflights and publishes Research Source, Document, and Collection Drafts together", async () => {
    const user = userEvent.setup();
    const documentDraft = seedDraft(canonicalContent.replace("selected phrase", "research note"));
    const sourceDraft = makeDraft("source", "research-paper", "schema_version: 1\nid: research-paper\ntype: paper\ntitle: Research Paper\n");
    const collectionDraft = makeDraft("collection", "continual-learning", "schema_version: 1\nid: continual-learning\ntitle: Continual Learning\nstatus: active\nposition: 0\nnodes: []\n");
    drafts.push(sourceDraft);
    drafts.push(collectionDraft);
    const navigate = vi.fn();
    renderWorkspace("quick-start", navigate, undefined, "continual-learning", [sourceDraft.id], "research-group");
    await screen.findByRole("heading", { name: "Quick Start" });

    await user.click(screen.getByRole("button", { name: "Publish All" }));
    await screen.findByRole("heading", { name: "变更摘要" });
    expect(api.preflightDraftsBatch).toHaveBeenCalledWith([
      { draft_id: documentDraft.id, expected_revision: documentDraft.revision },
      { draft_id: collectionDraft.id, expected_revision: collectionDraft.revision },
      { draft_id: sourceDraft.id, expected_revision: sourceDraft.revision },
    ]);
    await waitFor(() => expect((screen.getByRole("button", { name: /Publish All · 一个 Git 提交/ }) as HTMLButtonElement).disabled).toBe(false));
    await user.click(screen.getByRole("button", { name: /Publish All · 一个 Git 提交/ }));

    await waitFor(() => expect(api.publishDraftsBatch).toHaveBeenCalledOnce());
    expect(api.publishDraftsBatch.mock.calls[0][0]).toEqual([
      { draft_id: documentDraft.id, expected_revision: documentDraft.revision },
      { draft_id: collectionDraft.id, expected_revision: collectionDraft.revision },
      { draft_id: sourceDraft.id, expected_revision: sourceDraft.revision },
    ]);
    expect(api.publishDraft).not.toHaveBeenCalled();
    expect(navigate).toHaveBeenCalledWith("/documents/quick-start?collection=continual-learning");
  });

  it("refreshes Publish Review after a Draft-only stale revision and publishes the latest revision", async () => {
    const user = userEvent.setup();
    const reviewedDraft = seedDraft(canonicalContent.replace("selected phrase", "reviewed phrase"));
    api.publishDraft.mockImplementationOnce(async (id: string, expectedRevision: number) => {
      const current = drafts.find((draft) => draft.id === id);
      if (current?.revision !== expectedRevision) {
        throw Object.assign(
          new Error("Draft changed after review. Refresh the Publish Review before publishing."),
          { status: 409 },
        );
      }
      throw new Error("The stale revision guard should reject before publishing.");
    });
    renderWorkspace();

    await user.click(await screen.findByRole("button", { name: "发布" }));
    await screen.findByRole("heading", { name: "变更摘要" });
    const publishButton = await screen.findByRole("button", { name: "确认发布" });
    await waitFor(() => expect((publishButton as HTMLButtonElement).disabled).toBe(false));
    reviewedDraft.revision += 1;
    reviewedDraft.content = reviewedDraft.content.replace("reviewed phrase", "later revision");

    await user.click(publishButton);

    await waitFor(() => expect(api.publishDraft).toHaveBeenCalledWith(reviewedDraft.id, 1));
    await screen.findByRole("heading", { name: "变更摘要" });
    expect(screen.getByText(/Draft revision 2/)).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "查看完整差异" }));
    expect(screen.getByText(/later revision/)).toBeTruthy();
    const refreshedPublishButton = screen.getByRole("button", { name: "确认发布" });
    await waitFor(() => expect((refreshedPublishButton as HTMLButtonElement).disabled).toBe(false));
    await user.click(refreshedPublishButton);

    await waitFor(() => expect(api.publishDraft).toHaveBeenCalledWith(reviewedDraft.id, 2));
    expect(await screen.findByText("发布成功")).toBeTruthy();
  });

  it("opens Version Comparison when a fresh preflight finds a canonical conflict after 409", async () => {
    const user = userEvent.setup();
    const draft = seedDraft(canonicalContent.replace("selected phrase", "reviewed phrase"));
    api.publishDraft.mockImplementationOnce(async () => {
      conflictOnPreflight = true;
      throw Object.assign(new Error("Draft changed before publish."), { status: 409 });
    });
    renderWorkspace();

    await user.click(await screen.findByRole("button", { name: "发布" }));
    await screen.findByRole("heading", { name: "变更摘要" });
    const publishButton = await screen.findByRole("button", { name: "确认发布" });
    await waitFor(() => expect((publishButton as HTMLButtonElement).disabled).toBe(false));
    await user.click(publishButton);

    await waitFor(() => expect(api.publishDraft).toHaveBeenCalledWith(draft.id, 1));
    await screen.findByRole("heading", { name: "解决版本冲突" });
    expect(screen.queryByRole("heading", { name: "变更摘要" })).toBeNull();
  });

  it("formats a Reader text selection and autosaves the Markdown source change", async () => {
    const { container } = renderWorkspace();
    await screen.findByRole("heading", { name: "Quick Start" });
    selectParagraph(container);
    await userEvent.setup().click(await screen.findByRole("button", { name: "加粗" }));

    await waitFor(() => expect(api.createDraft).toHaveBeenCalledOnce(), { timeout: 2500 });
    expect(api.createDraft.mock.calls[0][2]).toContain("**A paragraph with a selected phrase.**");
  });

  it("disables source formatting for selections that cross Markdown blocks", async () => {
    const { container } = renderWorkspace();
    await screen.findByRole("heading", { name: "Quick Start" });
    selectAcrossReaderBlocks(container);

    expect((await screen.findByRole("button", { name: "加粗" })).hasAttribute("disabled")).toBe(true);
    expect(container.querySelector(".workspace-selection-format-note")?.textContent).toBe("格式修改仅支持单个 Markdown 区块内的选区。");
    expect(screen.getByRole("button", { name: "yellow 高亮" }).hasAttribute("disabled")).toBe(true);
  });

  it("does not guess source offsets for formatted Markdown or links", async () => {
    const formatted = renderWorkspace("formatted-note");
    await screen.findByRole("heading", { name: "Formatted Note" });
    selectWholeParagraph(formatted.container);
    expect((await screen.findByRole("button", { name: "加粗" })).hasAttribute("disabled")).toBe(true);
    expect(screen.getByText(/无法无歧义地对应 Markdown 源文/)).toBeTruthy();
    formatted.unmount();

    const linked = renderWorkspace("linked-note");
    await screen.findByRole("heading", { name: "Linked Note" });
    selectWholeParagraph(linked.container);
    expect((await screen.findByRole("button", { name: "加粗" })).hasAttribute("disabled")).toBe(true);
    expect(screen.getByText(/无法无歧义地对应 Markdown 源文/)).toBeTruthy();
  });

  it("disables source formatting when selected text occurs more than once in a block", async () => {
    const { container } = renderWorkspace("repeated-note");
    await screen.findByRole("heading", { name: "Repeated Note" });
    selectParagraphSubstring(container, "same text");

    expect((await screen.findByRole("button", { name: "加粗" })).hasAttribute("disabled")).toBe(true);
    expect(screen.getByText(/无法无歧义地对应 Markdown 源文/)).toBeTruthy();
  });

  it("keeps local content unsaved when another tab already created a different Draft, then saves an explicit merge", async () => {
    const user = userEvent.setup();
    const existing = makeDraft("document", "quick-start", canonicalContent + "\nOther tab content.\n");
    api.createDraft.mockImplementationOnce(async () => {
      drafts.push(existing);
      return { draft: existing, created: false };
    });
    const { container } = renderWorkspace();
    await screen.findByRole("heading", { name: "Quick Start" });
    await user.click(await screen.findByRole("button", { name: "编辑第 2 个区块" }));
    const editor = await screen.findByRole("textbox", { name: "Markdown 区块 2" });
    await user.clear(editor);
    await user.type(editor, "Local unsaved content.");
    await user.click(screen.getByRole("button", { name: "完成区块" }));

    await screen.findByRole("heading", { name: "Draft 内容冲突" });
    expect(screen.getAllByText(/另一个标签页已为此内容创建 Draft/).length).toBeGreaterThan(0);
    expect(screen.getByText(/Other tab content/)).toBeTruthy();
    expect(screen.getAllByText(/当前本地修改尚未保存/).length).toBeGreaterThan(0);
    expect(container.querySelector(".workspace-reader-save-state")?.textContent).toBe("Draft 冲突");

    const merge = screen.getByRole("textbox", { name: /手动合并内容/ });
    await user.clear(merge);
    await user.type(merge, "Merged content from both tabs.");
    await user.click(screen.getByRole("button", { name: "保存手动合并" }));

    await waitFor(() => expect(api.updateDraft).toHaveBeenCalledWith(existing.id, "Merged content from both tabs.", 1));
    await waitFor(() => expect(screen.queryByRole("heading", { name: "Draft 内容冲突" })).toBeNull());
  });

  it("separates a Runtime Draft revision conflict and keeps local content with a latest-revision CAS", async () => {
    const user = userEvent.setup();
    const existing = seedDraft();
    const otherTabContent = canonicalContent + "\nOther tab revision.\n";
    api.updateDraft.mockImplementationOnce(async () => {
      Object.assign(existing, { content: otherTabContent, revision: 2 });
      throw Object.assign(new Error("Draft revision changed"), {
        status: 409,
        code: "draft_revision_conflict",
        expected_revision: 1,
        current_revision: 2,
      });
    });
    renderWorkspace();
    await screen.findByRole("heading", { name: "Quick Start" });
    await user.click(await screen.findByRole("button", { name: "编辑第 2 个区块" }));
    const editor = await screen.findByRole("textbox", { name: "Markdown 区块 2" });
    await user.clear(editor);
    await user.type(editor, "Local revision.");
    await user.click(screen.getByRole("button", { name: "完成区块" }));

    await screen.findByRole("heading", { name: "Draft 内容冲突" });
    expect(screen.getAllByText(/Runtime Draft 已在另一个会话中更新/).length).toBeGreaterThan(0);
    expect(screen.getByText(/Other tab revision/)).toBeTruthy();
    expect(api.compareDraft).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "保留本地并保存" }));

    await waitFor(() => expect(api.updateDraft).toHaveBeenLastCalledWith(
      existing.id,
      expect.stringContaining("Local revision."),
      2,
    ));
    await waitFor(() => expect(screen.queryByRole("heading", { name: "Draft 内容冲突" })).toBeNull());
  });

  it("does not let a pending autosave from the previous entity write into the next entity", async () => {
    const user = userEvent.setup();
    const original = seedDraft();
    let resolvePending!: (draft: Draft) => void;
    const pendingSave = new Promise<Draft>((resolve) => { resolvePending = resolve; });
    api.updateDraft.mockImplementationOnce(() => pendingSave);
    render(<EntitySwitchHarness />);

    await screen.findByRole("heading", { name: "Quick Start" });
    await user.click(screen.getByRole("button", { name: "编辑第 2 个区块" }));
    const editor = await screen.findByRole("textbox", { name: "Markdown 区块 2" });
    await user.clear(editor);
    await user.type(editor, "A pending content.");
    await user.click(screen.getByRole("button", { name: "完成区块" }));
    await waitFor(() => expect(api.updateDraft).toHaveBeenCalledOnce(), { timeout: 2500 });

    await user.click(screen.getByRole("button", { name: "切换实体" }));
    await screen.findByRole("heading", { name: "Second Note" });
    expect(await screen.findByText("Second entity content.")).toBeTruthy();

    await act(async () => {
      resolvePending({ ...original, content: canonicalContent.replace(canonicalBody, "# Main heading\n\nA pending content."), revision: 2 });
      await pendingSave;
    });

    expect(api.updateDraft).toHaveBeenCalledTimes(1);
    expect(api.updateDraft.mock.calls[0][0]).toBe(original.id);
    expect(api.updateDraft.mock.calls[0][1]).toContain("A pending content.");
    expect(screen.getByText("Second entity content.")).toBeTruthy();
    expect(api.createDraft).not.toHaveBeenCalled();
  });

  it("saves a Reader selection as a Presentation Annotation without editing Markdown", async () => {
    const user = userEvent.setup();
    const { container } = renderWorkspace();
    await screen.findByRole("heading", { name: "Quick Start" });
    selectParagraph(container);
    await user.click(await screen.findByRole("button", { name: "yellow 高亮" }));

    await waitFor(() => expect(api.createPresentationAnnotation).toHaveBeenCalledOnce());
    expect(api.createPresentationAnnotation.mock.calls[0][0]).toMatchObject({
      entity_type: "document",
      entity_id: "quick-start",
      style_type: "highlight",
      style_value: "yellow",
      selected_text: "A paragraph with a selected phrase.",
    });
    expect(api.createDraft).not.toHaveBeenCalled();
  });

  it("sends the selected Reader text as the AI selection only after consent", async () => {
    const user = userEvent.setup();
    const { container } = renderWorkspace();
    await screen.findByRole("heading", { name: "Quick Start" });
    selectParagraph(container);
    await user.click(await screen.findByRole("button", { name: "Ask AI" }));

    const selection = await screen.findByRole("textbox", { name: "AI 选区" });
    expect((selection as HTMLTextAreaElement).value).toBe("A paragraph with a selected phrase.");
    await user.click(screen.getByRole("checkbox", { name: /我同意将此选区/ }));
    await user.click(screen.getByRole("button", { name: "Ask AI" }));
    await waitFor(() => expect(api.requestAIProposal).toHaveBeenCalledOnce());
    expect(api.requestAIProposal.mock.calls[0][0]).toBe("selection-review");
    expect(api.requestAIProposal.mock.calls[0][2]).toBe("A paragraph with a selected phrase.");
  });

  it("recovers a Document Draft conflict by deleting the Draft and reloading Canonical", async () => {
    const user = userEvent.setup();
    const oldContent = canonicalContent.replace("selected phrase", "old phrase");
    const draft = seedDraft(oldContent);
    conflictOnPreflight = true;
    renderWorkspace();

    await user.click(await screen.findByRole("button", { name: "发布" }));
    await screen.findByRole("heading", { name: "解决版本冲突" });
    expect((screen.getByRole("button", { name: "丢弃 Draft" }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText("请等待保存完成或先处理冲突")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "放弃 Draft 并载入当前正式版" }));

    await waitFor(() => expect(api.discardDraft).toHaveBeenCalledWith(draft.id, draft.revision));
    const paragraph = await screen.findByText("A paragraph with a selected phrase.");
    expect(paragraph.closest(".workspace-inline-block")).not.toBeNull();
  });
});
