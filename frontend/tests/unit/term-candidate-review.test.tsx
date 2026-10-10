import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import { TermCandidateReview } from "../../src/pages/TermCandidateReview";
import { applyProposalToDraft, discardDraft, listProposals, preflightDraft, publishDraft, rejectProposal, rejectTermCandidate, requestCandidateTermDraftProposal, requestTermRewrite, type Draft, type Proposal, type TermCandidate } from "../../src/api";

const state = vi.hoisted(() => ({ content: "---\nschema_version: 1\nid: replay\ntitle: Replay\ntype: concept\ndepth: stub\n---\n# Replay\n\n## 一、中文解释\n\nExperience Replay retains examples.\n" }));
const api = vi.hoisted(() => ({
  applyProposalToDraft: vi.fn(),
  discardDraft: vi.fn(),
  listProposals: vi.fn(),
  preflightDraft: vi.fn(),
  publishDraft: vi.fn(),
  rejectProposal: vi.fn(),
  rejectTermCandidate: vi.fn(),
  requestCandidateTermDraftProposal: vi.fn(),
  requestTermRewrite: vi.fn(),
}));

vi.mock("../../src/api", async (importOriginal) => ({ ...(await importOriginal<typeof import("../../src/api")>()), ...api }));
vi.mock("../../src/reader/readerModel", () => ({ hashText: vi.fn().mockResolvedValue("hash") }));
vi.mock("../../src/draft/useRuntimeDraftSession", () => ({
  useRuntimeDraftSession: () => ({
    content: state.content,
    loading: false,
    state: "saved",
    error: "",
    getCurrentContent: () => state.content,
    updateContent: (value: string) => { state.content = value; },
    saveNow: async () => makeSeed(),
    acceptDraft: (draft: Draft) => { state.content = draft.content; },
  }),
}));

const initialContent = "---\nschema_version: 1\nid: replay\ntitle: Replay\ntype: concept\ndepth: stub\n---\n# Replay\n\n## 一、中文解释\n\nExperience Replay retains examples.\n";

function makeSeed(content = state.content): Draft {
  return { id: "d", entity_type: "term", entity_id: "replay", content, working_content_hash: "hash", revision: 2, base_git_revision: "base", base_content_hash: "canonical-hash", created_at: "2026-10-10T00:00:00Z", updated_at: "2026-10-10T00:00:00Z" };
}

function makeProposal(content = "---\nschema_version: 1\nid: replay\ntitle: Replay\ntype: concept\ndepth: stub\n---\n# Replay\n\n## 一、中文解释\n\nSuggested explanation.\n"): Proposal {
  return { id: "proposal-1", target_type: "term", target_id: "replay", kind: "term-draft", status: "proposed", base_content_hash: "hash", payload: { draft_id: "d", content }, diff_text: null, created_by: "ai", provider: "mock", model: "test", created_at: "2026-10-10T00:00:00Z", reviewed_at: null, review_note: null };
}

function renderReview(onDone = vi.fn(), seed = makeSeed()) {
  return render(<TermCandidateReview candidate={{ id: "candidate-1", display_name: "Replay" } as TermCandidate} seed={seed} onDone={onDone} />);
}

beforeEach(() => {
  state.content = initialContent;
  vi.clearAllMocks();
  api.listProposals.mockResolvedValue([]);
  api.preflightDraft.mockResolvedValue({ draft_id: "d", valid: true, conflict: false, errors: [], warnings: [] });
  api.publishDraft.mockResolvedValue({ draft_id: "d", entity_type: "term", entity_id: "replay", commit_revision: "commit", warnings: [] });
  api.applyProposalToDraft.mockImplementation(async (_proposalId: string, _draftId: string, _revision: number) => ({ proposal: makeProposal(), draft: { ...makeSeed(), revision: 3 } }));
  api.discardDraft.mockResolvedValue(undefined);
  api.rejectProposal.mockResolvedValue(undefined);
  api.rejectTermCandidate.mockResolvedValue(undefined);
  api.requestCandidateTermDraftProposal.mockResolvedValue({ proposal: makeProposal(), external_provider_notice: "sent" });
});

test("one approval marks human review, preflights and publishes the reviewed revision", async () => {
  const done = vi.fn();
  renderReview(done);
  fireEvent.click(screen.getByRole("button", { name: "通过", exact: true }));
  await waitFor(() => expect(done).toHaveBeenCalled());
  expect(state.content).toContain("status: approved");
  expect(preflightDraft).toHaveBeenCalledWith("d");
  expect(publishDraft).toHaveBeenCalledWith("d", 2);
});

test("a publish conflict keeps the reviewed Draft and never reports approval", async () => {
  const done = vi.fn();
  api.publishDraft.mockRejectedValue(new Error("正式版已变化"));
  renderReview(done);
  fireEvent.click(screen.getByRole("button", { name: "通过", exact: true }));
  await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("正式版已变化"));
  expect(done).not.toHaveBeenCalled();
  expect(state.content).toContain("Experience Replay retains examples.");
});

test("shows why rewrite is disabled, then reports loading and keeps input after an error", async () => {
  renderReview();
  const rewrite = screen.getByRole("button", { name: "AI 重写", exact: true });
  expect((rewrite as HTMLButtonElement).disabled).toBe(true);
  expect(screen.getByText("请输入重写要求。")).toBeTruthy();

  const requirements = screen.getByLabelText("AI 重写要求");
  fireEvent.change(requirements, { target: { value: "解释向量维度和用途" } });
  api.requestTermRewrite.mockImplementationOnce(() => new Promise((_resolve, reject) => setTimeout(() => reject(new Error("AI service unavailable")), 30)));
  fireEvent.click(rewrite);
  expect(await screen.findByRole("button", { name: "正在重写…" })).toBeTruthy();
  expect((rewrite as HTMLButtonElement).disabled).toBe(true);
  await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("AI service unavailable"));
  expect((requirements as HTMLTextAreaElement).value).toBe("解释向量维度和用途");
  expect(screen.getByText("操作失败。已保留当前编辑和建议内容，可检查错误后重试。")).toBeTruthy();
});

test("reuses a matching cached proposal and compares the old body with the unadopted suggestion", async () => {
  const proposal = makeProposal();
  api.listProposals.mockResolvedValue([proposal]);
  renderReview(vi.fn(), makeSeed());

  expect(await screen.findByText(/已载入与当前 Draft 匹配的建议/)).toBeTruthy();
  const oldBody = screen.getByRole("region", { name: "当前 Term Draft 原文" });
  const newBody = screen.getByRole("region", { name: "尚未采用的 AI 建议" });
  expect(oldBody.textContent).toContain("Experience Replay retains examples.");
  expect(newBody.textContent).toContain("Suggested explanation.");
  expect(oldBody.querySelector("h1")).toBeNull();
  expect(newBody.querySelector("h1")).toBeNull();

  fireEvent.click(screen.getByRole("button", { name: "AI 生成双语解释" }));
  await waitFor(() => expect(screen.getByText(/已复用与当前 Draft 内容匹配的双语建议/)).toBeTruthy());
  expect(requestCandidateTermDraftProposal).not.toHaveBeenCalled();
  expect(requestTermRewrite).not.toHaveBeenCalled();
});

test("adoption only updates the Draft and keeps Publish as a separate human action", async () => {
  const proposal = makeProposal();
  api.listProposals.mockResolvedValue([proposal]);
  renderReview();
  await screen.findByRole("region", { name: "尚未采用的 AI 建议" });
  fireEvent.click(screen.getByRole("button", { name: "采用到 Draft" }));

  expect(await screen.findByText("建议已采用到 Term Draft；仍需检查并单独发布。")).toBeTruthy();
  expect(applyProposalToDraft).toHaveBeenCalledWith("proposal-1", "d", 2);
  expect(publishDraft).not.toHaveBeenCalled();
});

test("rejects the Candidate only after discarding its Draft", async () => {
  const done = vi.fn();
  renderReview(done);
  fireEvent.click(screen.getByRole("button", { name: "拒绝", exact: true }));
  await waitFor(() => expect(done).toHaveBeenCalledOnce());
  expect(discardDraft).toHaveBeenCalledWith("d", 2);
  expect(rejectTermCandidate).toHaveBeenCalledWith("candidate-1", { scope: "global" });
  expect(publishDraft).not.toHaveBeenCalled();
});
