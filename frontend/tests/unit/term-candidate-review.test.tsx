import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import { TermCandidateReview } from "../../src/pages/TermCandidateReview";
import { applyProposalToDraft, discardDraft, listProposals, preflightDraft, publishDraft, rejectProposal, rejectTermCandidate, requestCandidateTermDraftProposal, requestTermRewrite, type Draft, type Proposal, type TermCandidate } from "../../src/api";

const state = vi.hoisted(() => ({ content: "---\nschema_version: 1\nid: replay\ntitle: Replay\ntype: concept\ndepth: stub\naliases: [Experience Replay]\nsources: [replay-paper]\n---\n# Replay\n\nUser-written context remains untouched.\n\n## 一、中文解释\n\nExperience Replay retains examples.\n" }));
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

const initialContent = "---\nschema_version: 1\nid: replay\ntitle: Replay\ntype: concept\ndepth: stub\naliases: [Experience Replay]\nsources: [replay-paper]\n---\n# Replay\n\nUser-written context remains untouched.\n\n## 一、中文解释\n\nExperience Replay retains examples.\n";

function makeSeed(content = state.content): Draft {
  return { id: "d", entity_type: "term", entity_id: "replay", content, working_content_hash: "hash", revision: 2, base_git_revision: "base", base_content_hash: "canonical-hash", created_at: "2026-10-10T00:00:00Z", updated_at: "2026-10-10T00:00:00Z" };
}

function makeProposal(content = "---\nschema_version: 1\nid: replay\ntitle: Replay\ntype: concept\ndepth: stub\n---\n# Replay\n\n## 一、中文解释\n\nSuggested Chinese explanation.\n\n## 二、English Explanation\n\nSuggested English explanation.\n"): Proposal {
  return { id: "proposal-1", target_type: "term", target_id: "replay", kind: "term-draft", status: "proposed", base_content_hash: "hash", payload: { task: "draft_term", draft_id: "d", content, result: { definition_zh: "Suggested Chinese explanation.", definition_en: "Suggested English explanation.", rationale: "Both languages cover the same core idea." } }, diff_text: null, created_by: "ai", provider: "mock", model: "test", created_at: "2026-10-10T00:00:00Z", reviewed_at: null, review_note: null };
}

function renderReview(onDone = vi.fn(), seed = makeSeed(), onClose = vi.fn()) {
  return render(<TermCandidateReview candidate={{ id: "candidate-1", display_name: "Replay" } as TermCandidate} seed={seed} onClose={onClose} onDone={onDone} />);
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

test("shows the saved standard depth and explains its added detail", async () => {
  const standardContent = initialContent.replace("depth: stub", "depth: standard");
  state.content = standardContent;
  renderReview(vi.fn(), makeSeed(standardContent));

  const depth = await screen.findByRole("combobox", { name: "解释深度" });
  await waitFor(() => expect((depth as HTMLSelectElement).disabled).toBe(false));
  expect((depth as HTMLSelectElement).value).toBe("standard");
  expect(screen.getByRole("option", { name: "标准理解（默认）" })).toBeTruthy();
  expect(screen.getByText("在完整基础上解释关键机制、流程、关系或输入输出。")).toBeTruthy();
});

test("closes the inline review only after saving the current Draft", async () => {
  const onClose = vi.fn();
  renderReview(vi.fn(), makeSeed(), onClose);

  fireEvent.click(screen.getByRole("button", { name: "关闭编辑" }));

  await waitFor(() => expect(onClose).toHaveBeenCalledOnce());
});

test("saves a selected depth before generation without changing other Draft content", async () => {
  renderReview();
  const depth = await screen.findByRole("combobox", { name: "解释深度" });
  await waitFor(() => expect((depth as HTMLSelectElement).disabled).toBe(false));

  fireEvent.change(depth, { target: { value: "deep" } });

  expect(await screen.findByText("深度已保存为「系统深入」；后续生成会读取当前 Draft。")).toBeTruthy();
  expect(state.content).toBe(initialContent.replace("depth: stub", "depth: deep"));
  api.requestCandidateTermDraftProposal.mockImplementation(async (draftId: string, candidateId: string) => {
    expect(draftId).toBe("d");
    expect(candidateId).toBe("candidate-1");
    expect(state.content).toContain("depth: deep");
    expect(state.content).toContain("User-written context remains untouched.");
    expect(state.content).toContain("aliases: [Experience Replay]");
    return { proposal: makeProposal(), external_provider_notice: "sent" };
  });

  fireEvent.click(screen.getByRole("button", { name: "重新生成双语解释" }));
  await waitFor(() => expect(requestCandidateTermDraftProposal).toHaveBeenCalledWith("d", "candidate-1"));
});

test("reopening the review reads the selected depth from the saved Draft", async () => {
  state.content = initialContent.replace("depth: stub", "depth: deep");
  const first = renderReview();
  const firstSelector = await screen.findByRole("combobox", { name: "解释深度" });
  await waitFor(() => expect((firstSelector as HTMLSelectElement).disabled).toBe(false));
  expect((firstSelector as HTMLSelectElement).value).toBe("deep");

  first.unmount();
  renderReview();
  const reopenedSelector = await screen.findByRole("combobox", { name: "解释深度" });
  await waitFor(() => expect((reopenedSelector as HTMLSelectElement).disabled).toBe(false));
  expect((reopenedSelector as HTMLSelectElement).value).toBe("deep");
});

test("an unhandled Proposal blocks depth changes until it is adopted or discarded", async () => {
  const proposal = makeProposal();
  api.listProposals.mockResolvedValue([proposal]);
  renderReview();
  const depth = await screen.findByRole("combobox", { name: "解释深度" });

  expect(await screen.findByText("请先采用或放弃当前建议，再更改深度。")).toBeTruthy();
  expect((depth as HTMLSelectElement).disabled).toBe(true);
  fireEvent.change(depth, { target: { value: "deep" } });
  expect(state.content).toBe(initialContent);
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

test("repairs only current Draft H3 numbering without AI and then allows Publisher flow", async () => {
  const done = vi.fn();
  const draftContent = initialContent.replace(
    "Experience Replay retains examples.",
    "### 9. Meaning\n\nChinese body stays exact.\n\n### Example\n\nExample body stays exact.\n\n```markdown\n### Example in code\n```\n\n## 二、English Explanation\n\n### 8. Meaning\n\nEnglish body stays exact.\n",
  );
  state.content = draftContent;
  renderReview(done, makeSeed(draftContent));

  await waitFor(() => expect((screen.getByRole("button", { name: /修正 H3 编号/ }) as HTMLButtonElement).disabled).toBe(false));
  fireEvent.click(screen.getByRole("button", { name: "修正 H3 编号（3 处）" }));

  expect(await screen.findByText("已只修正 3 个 H3 标题编号；解释正文保持不变，Draft 已保存，可检查后发布。")).toBeTruthy();
  expect(state.content).toContain("### 1. Meaning\n\nChinese body stays exact.");
  expect(state.content).toContain("### 2. Example\n\nExample body stays exact.");
  expect(state.content).toContain("## 二、English Explanation\n\n### 1. Meaning\n\nEnglish body stays exact.");
  expect(state.content).toContain("```markdown\n### Example in code\n```");
  expect(state.content).toContain("aliases: [Experience Replay]");
  expect(requestCandidateTermDraftProposal).not.toHaveBeenCalled();
  expect(requestTermRewrite).not.toHaveBeenCalled();

  fireEvent.click(screen.getByRole("button", { name: "通过", exact: true }));
  await waitFor(() => expect(done).toHaveBeenCalledOnce());
  expect(preflightDraft).toHaveBeenCalledWith("d");
  expect(publishDraft).toHaveBeenCalledWith("d", 2);
});

test("summarizes repeated H3 preflight errors and keeps their details expandable", async () => {
  const repeatedIssue = "heading.h3_numbering: H3 headings must use Arabic numbering followed by '. '.";
  api.preflightDraft.mockResolvedValue({
    draft_id: "d", valid: false, conflict: false,
    errors: [`Markdown validation failed: ${Array.from({ length: 8 }, () => repeatedIssue).join("; ")}`],
    warnings: [],
  });
  renderReview();
  fireEvent.click(screen.getByRole("button", { name: "通过", exact: true }));

  const alert = await screen.findByRole("alert");
  expect(alert.textContent).toBe("标题格式：8 个 H3 缺少“1. ”编号（可修正后重试）");
  const details = screen.getByText("查看 Preflight 详情").closest("details");
  expect(details?.open).toBe(false);
  expect(details?.textContent?.match(/heading\.h3_numbering:/g)).toHaveLength(8);
  expect(publishDraft).not.toHaveBeenCalled();
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

test("keeps the rewrite requirement after a request error", async () => {
  renderReview();
  await waitFor(() => expect((screen.getByRole("combobox", { name: "解释深度" }) as HTMLSelectElement).disabled).toBe(false));
  const rewrite = screen.getByRole("button", { name: "AI 双语重写", exact: true });
  expect((rewrite as HTMLButtonElement).disabled).toBe(false);

  const requirements = screen.getByLabelText("AI 重写要求（可选）");
  fireEvent.change(requirements, { target: { value: "解释向量维度和用途" } });
  api.requestTermRewrite.mockImplementationOnce(() => new Promise((_resolve, reject) => setTimeout(() => reject(new Error("AI service unavailable")), 30)));
  fireEvent.click(rewrite);
  expect(await screen.findByRole("button", { name: "正在重写…" })).toBeTruthy();
  expect((rewrite as HTMLButtonElement).disabled).toBe(true);
  await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("AI service unavailable"));
  expect(requestTermRewrite).toHaveBeenCalledWith("d", "解释向量维度和用途");
  expect((requirements as HTMLTextAreaElement).value).toBe("解释向量维度和用途");
  expect(screen.getByText("操作失败。已保留当前编辑和建议内容，可检查错误后重试。")).toBeTruthy();
});

test("sends a bilingual rewrite when the optional requirement is empty", async () => {
  api.requestTermRewrite.mockResolvedValue({ proposal: makeProposal(), external_provider_notice: "sent" });
  renderReview();
  await waitFor(() => expect((screen.getByRole("combobox", { name: "解释深度" }) as HTMLSelectElement).disabled).toBe(false));
  fireEvent.click(screen.getByRole("button", { name: "AI 双语重写", exact: true }));

  expect(await screen.findByRole("region", { name: "尚未采用的双语重写建议" })).toBeTruthy();
  expect(requestTermRewrite).toHaveBeenCalledWith("d", "");
});

test("reuses a matching cached proposal and compares the old body with the unadopted suggestion", async () => {
  const proposal = makeProposal();
  api.listProposals.mockResolvedValue([proposal]);
  renderReview(vi.fn(), makeSeed());

  expect(await screen.findByText(/已载入与当前 Draft 匹配的建议/)).toBeTruthy();
  const oldBody = screen.getByRole("region", { name: "当前 Term Draft 原文" });
  const newBody = screen.getByRole("region", { name: "尚未采用的双语重写建议" });
  expect(oldBody.textContent).toContain("Experience Replay retains examples.");
  expect(newBody.textContent).toContain("Suggested Chinese explanation.");
  expect(newBody.textContent).toContain("Suggested English explanation.");
  expect(oldBody.querySelector("h1")).toBeNull();
  expect(newBody.querySelector("h1")).toBeNull();

  fireEvent.click(screen.getByRole("button", { name: "重新生成双语解释" }));
  await waitFor(() => expect(screen.getByText(/已复用与当前 Draft 内容匹配的双语建议/)).toBeTruthy());
  expect(requestCandidateTermDraftProposal).not.toHaveBeenCalled();
  expect(requestTermRewrite).not.toHaveBeenCalled();
});

test("shows an initial bilingual proposal without an empty comparison column", async () => {
  const blankContent = initialContent.replace(/\nUser-written context remains untouched\.[\s\S]*$/, "\n");
  state.content = blankContent;
  api.listProposals.mockResolvedValue([makeProposal()]);
  renderReview(vi.fn(), makeSeed(blankContent));

  expect(await screen.findByText("初次生成：当前 Draft 没有原文。")).toBeTruthy();
  expect(screen.getByRole("region", { name: "尚未采用的双语重写建议" }).textContent).toContain("Suggested Chinese explanation.");
  expect(screen.getByRole("region", { name: "尚未采用的双语重写建议" }).textContent).toContain("Suggested English explanation.");
  expect(screen.queryByRole("region", { name: "当前 Term Draft 原文" })).toBeNull();
});

test("does not offer an older single-language rewrite as a bilingual Proposal", async () => {
  const singleLanguageProposal = makeProposal();
  singleLanguageProposal.payload.task = "rewrite_term_language";
  api.listProposals.mockResolvedValue([singleLanguageProposal]);
  renderReview();

  await waitFor(() => expect((screen.getByRole("button", { name: "重新生成双语解释" }) as HTMLButtonElement).disabled).toBe(false));
  expect(screen.queryByRole("region", { name: "尚未采用的双语重写建议" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "重新生成双语解释" }));

  await waitFor(() => expect(requestCandidateTermDraftProposal).toHaveBeenCalledWith("d", "candidate-1"));
});

test("adoption only updates the Draft and keeps Publish as a separate human action", async () => {
  const proposal = makeProposal();
  api.listProposals.mockResolvedValue([proposal]);
  renderReview();
  await screen.findByRole("region", { name: "尚未采用的双语重写建议" });
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
