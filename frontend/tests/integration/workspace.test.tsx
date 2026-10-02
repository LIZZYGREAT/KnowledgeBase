import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { WorkspacePage } from "../../src/Workspace";
import type { Draft, EntityDetail, PresentationAnnotation } from "../../src/api";

const api = vi.hoisted(() => ({
  getEntity: vi.fn(),
  getCollectionNavigation: vi.fn(),
  listDrafts: vi.fn(),
  createDraft: vi.fn(),
  updateDraft: vi.fn(),
  discardDraft: vi.fn(),
  compareDraft: vi.fn(),
  preflightDraft: vi.fn(),
  publishDraft: vi.fn(),
  publishDraftsBatch: vi.fn(),
  listProposals: vi.fn(),
  listAllEntities: vi.fn(),
  recordDocumentOpen: vi.fn(),
  listPresentationAnnotations: vi.fn(),
  createPresentationAnnotation: vi.fn(),
  deletePresentationAnnotation: vi.fn(),
  requestAIProposal: vi.fn(),
  reviewProposal: vi.fn(),
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
let annotations: PresentationAnnotation[];
let draftSequence: number;
let conflictOnPreflight: boolean;

function makeEntity(id = "quick-start"): EntityDetail {
  const title = id === "second-note" ? "Second Note" : "Quick Start";
  const body = id === "second-note" ? "# Second heading\n\nSecond entity content." : canonicalBody;
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
    if (type === "document" && ["quick-start", "second-note"].includes(id)) return makeEntity(id);
    throw Object.assign(new Error("Not found"), { status: 404 });
  });
  api.getCollectionNavigation.mockResolvedValue(null);
  api.listDrafts.mockImplementation(async (type: string, id: string) => drafts.filter((draft) => draft.entity_type === type && draft.entity_id === id));
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
  api.publishDraft.mockImplementation(async (id: string) => ({
    draft_id: id,
    entity_type: "document",
    entity_id: "quick-start",
    commit_revision: "publish-revision",
    proposal_id: null,
    warnings: [],
  }));
  api.publishDraftsBatch.mockResolvedValue({ results: [], commit_revision: "batch-revision", warnings: [] });
  api.listProposals.mockResolvedValue([]);
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
  api.requestAIProposal.mockResolvedValue({
    proposal: {
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
    },
    external_provider_notice: "Selection sent for review.",
  });
  api.reviewProposal.mockResolvedValue(undefined);
}

function renderWorkspace(initialMode: "read" | "edit" = "read") {
  return render(<WorkspacePage type="document" id="quick-start" navigate={vi.fn()} initialMode={initialMode} />);
}

function EntitySwitchHarness() {
  const [id, setId] = useState("quick-start");
  return <>
    <button type="button" onClick={() => setId("second-note")}>切换实体</button>
    <WorkspacePage type="document" id={id} navigate={vi.fn()} initialMode="edit" />
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

describe("Workspace React integration", () => {
  beforeEach(() => {
    drafts = [];
    annotations = [];
    draftSequence = 0;
    conflictOnPreflight = false;
    vi.clearAllMocks();
    installApiBehavior();
  });

  it("keeps reading and inline editing in one Workspace, autosaves, then publishes through the review drawer", async () => {
    const user = userEvent.setup();
    const { container } = renderWorkspace();
    await screen.findByRole("heading", { name: "Quick Start" });

    await user.click(await screen.findByRole("button", { name: "编辑第 2 个区块" }));
    const editor = await screen.findByRole("textbox", { name: "Markdown 区块 2" });
    await user.clear(editor);
    await user.type(editor, "Revised paragraph.");
    expect((editor as HTMLTextAreaElement).value).toBe("Revised paragraph.");
    await user.click(screen.getByRole("button", { name: "完成区块" }));
    await waitFor(() => expect(drafts[0]?.content).toContain("Revised paragraph."), { timeout: 2500 });

    await user.click(screen.getByRole("button", { name: "完整编辑器" }));
    expect(container.querySelector(".workspace-shell")).not.toBeNull();
    await user.click(await screen.findByRole("button", { name: "发布" }));
    await screen.findByRole("heading", { name: "变更摘要" });
    const publishButton = await screen.findByRole("button", { name: "确认发布" });
    await waitFor(() => expect((publishButton as HTMLButtonElement).disabled).toBe(false));
    await user.click(publishButton);
    await waitFor(() => expect(api.publishDraft).toHaveBeenCalledOnce());
  });

  it("formats a Reader text selection and autosaves the Markdown source change", async () => {
    const { container } = renderWorkspace();
    await screen.findByRole("heading", { name: "Quick Start" });
    selectParagraph(container);
    await userEvent.setup().click(await screen.findByRole("button", { name: "加粗" }));

    await waitFor(() => expect(api.createDraft).toHaveBeenCalledOnce(), { timeout: 2500 });
    expect(api.createDraft.mock.calls[0][2]).toContain("**A paragraph with a selected phrase.**");
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

  it("does not let a pending autosave from the previous entity write into the next entity", async () => {
    const user = userEvent.setup();
    const original = seedDraft();
    let resolvePending!: (draft: Draft) => void;
    const pendingSave = new Promise<Draft>((resolve) => { resolvePending = resolve; });
    api.updateDraft.mockImplementationOnce(() => pendingSave);
    render(<EntitySwitchHarness />);

    await screen.findByRole("heading", { name: "编辑 quick-start" });
    await user.click(screen.getAllByRole("button", { name: "编辑区块" })[1]);
    const editor = await screen.findByRole("textbox", { name: "Markdown 区块 2" });
    await user.clear(editor);
    await user.type(editor, "A pending content.");
    await user.click(screen.getByRole("button", { name: "完成区块" }));
    await user.click(screen.getByRole("button", { name: "保存草稿" }));
    await waitFor(() => expect(api.updateDraft).toHaveBeenCalledOnce());

    await user.click(screen.getByRole("button", { name: "切换实体" }));
    await screen.findByRole("heading", { name: "编辑 second-note" });
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
    renderWorkspace("edit");

    await user.click(await screen.findByRole("button", { name: "发布" }));
    await screen.findByRole("heading", { name: "解决版本冲突" });
    await user.click(screen.getByRole("button", { name: "放弃 Draft 并载入当前正式版" }));

    await waitFor(() => expect(api.discardDraft).toHaveBeenCalledWith(draft.id, draft.revision));
    const paragraph = await screen.findByText("A paragraph with a selected phrase.");
    expect(paragraph.closest(".markdown-block")).not.toBeNull();
  });
});
