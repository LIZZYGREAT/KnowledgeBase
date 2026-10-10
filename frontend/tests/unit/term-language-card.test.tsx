import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import { TermLanguageCard } from "../../src/reader/TermLanguageCard";
import type { WorkspaceDraftController } from "../../src/useWorkspaceDraft";
import { rejectProposal, requestTermRewrite, type Draft, type Proposal } from "../../src/api";

const api = vi.hoisted(() => ({ rejectProposal: vi.fn(), requestTermRewrite: vi.fn() }));
vi.mock("../../src/api", () => api);

const body = "# EWC\n\n## 一、中文解释\n\nFisher Information 约束参数。\n";

function makeProposal(explanation = "新解释说明参数重要性如何影响训练。"): Proposal {
  return {
    id: "rewrite-proposal",
    target_type: "term",
    target_id: "ewc",
    kind: "document_revision",
    status: "proposed",
    base_content_hash: "hash",
    payload: { result: { explanation, rationale: "Clarifies the mechanism." } },
    diff_text: null,
    created_by: "ai",
    provider: "mock",
    model: "test",
    created_at: "2026-10-10T00:00:00Z",
    reviewed_at: null,
    review_note: null,
  };
}

function makeWorkspace() {
  let content = `---\nschema_version: 1\nid: ewc\ntitle: EWC\ntype: concept\ndepth: stub\n---\n${body}`;
  const draft: Draft = { id: "draft-ewc", entity_type: "term", entity_id: "ewc", content, revision: 3, base_git_revision: "base", base_content_hash: "canonical-hash", created_at: "2026-10-10T00:00:00Z", updated_at: "2026-10-10T00:00:00Z" };
  const workspace = {
    getCurrentContent: () => content,
    updateContent: vi.fn((next: string) => { content = next; }),
    saveNow: vi.fn(async () => ({ ...draft, content })),
    ensureDraft: vi.fn(async () => ({ ...draft, content })),
    applyProposalToDraft: vi.fn(async () => undefined),
  } as unknown as WorkspaceDraftController;
  return workspace;
}

beforeEach(() => {
  vi.clearAllMocks();
  api.rejectProposal.mockResolvedValue(undefined);
});

test("language switches show missing-language feedback without AI or Draft writes", () => {
  const workspace = makeWorkspace();
  render(<TermLanguageCard body={body} workspace={workspace} navigate={vi.fn()} disabled={false} />);
  fireEvent.click(screen.getByRole("button", { name: "English", exact: true }));
  expect(screen.getByText(/暂无 English解释/)).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "中文", exact: true }));
  expect(requestTermRewrite).not.toHaveBeenCalled();
  expect(workspace.updateContent).not.toHaveBeenCalled();
});

test("explains disabled rewrite, shows request progress and compares the old text with the unadopted suggestion", async () => {
  const workspace = makeWorkspace();
  render(<TermLanguageCard body={body} workspace={workspace} navigate={vi.fn()} disabled={false} />);
  fireEvent.click(screen.getByRole("button", { name: "AI 重写", exact: true }));
  const rewrite = screen.getByRole("button", { name: "生成当前语言建议" });
  expect((rewrite as HTMLButtonElement).disabled).toBe(true);
  expect(screen.getByText("请输入重写要求。")).toBeTruthy();
  fireEvent.change(screen.getByLabelText("重写要求"), { target: { value: "Explain the role of Fisher Information." } });

  let resolveRequest!: (value: { proposal: Proposal; external_provider_notice: string }) => void;
  api.requestTermRewrite.mockReturnValueOnce(new Promise((resolve) => { resolveRequest = resolve; }));
  fireEvent.click(rewrite);
  expect(await screen.findByRole("button", { name: "正在生成…" })).toBeTruthy();
  expect((rewrite as HTMLButtonElement).disabled).toBe(true);
  resolveRequest({ proposal: makeProposal(), external_provider_notice: "sent" });

  expect(await screen.findByRole("region", { name: "重写前解释" })).toBeTruthy();
  expect(screen.getByRole("region", { name: "重写前解释" }).textContent).toContain("Fisher Information 约束参数。");
  expect(screen.getByRole("region", { name: "尚未采用的重写建议" }).textContent).toContain("新解释说明参数重要性如何影响训练。");
  expect(screen.getByText(/当前 Draft 和正式知识尚未改变/)).toBeTruthy();
  expect((screen.getByRole("button", { name: "English", exact: true }) as HTMLButtonElement).disabled).toBe(true);
});

test("keeps the request text after failure and exposes the error beside the action", async () => {
  const workspace = makeWorkspace();
  render(<TermLanguageCard body={body} workspace={workspace} navigate={vi.fn()} disabled={false} />);
  fireEvent.click(screen.getByRole("button", { name: "AI 重写", exact: true }));
  const requirements = screen.getByLabelText("重写要求");
  fireEvent.change(requirements, { target: { value: "Clarify the mechanism." } });
  api.requestTermRewrite.mockRejectedValueOnce(new Error("DeepSeek unavailable"));
  fireEvent.click(screen.getByRole("button", { name: "生成当前语言建议" }));

  await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("DeepSeek unavailable"));
  expect((requirements as HTMLTextAreaElement).value).toBe("Clarify the mechanism.");
  expect(screen.getByText("重写失败；输入仍保留，可检查错误后重试。")).toBeTruthy();
});

test("adopts or rejects only the Proposal and leaves publishing to Workspace", async () => {
  const workspace = makeWorkspace();
  api.requestTermRewrite.mockResolvedValue({ proposal: makeProposal(), external_provider_notice: "sent" });
  const view = render(<TermLanguageCard body={body} workspace={workspace} navigate={vi.fn()} disabled={false} />);
  fireEvent.click(screen.getByRole("button", { name: "AI 重写", exact: true }));
  fireEvent.change(screen.getByLabelText("重写要求"), { target: { value: "Explain the mechanism." } });
  fireEvent.click(screen.getByRole("button", { name: "生成当前语言建议" }));
  fireEvent.click(await screen.findByRole("button", { name: "采用到 Draft" }));
  expect(await screen.findByText("建议已采用到 Term Draft；仍需检查并单独发布。")).toBeTruthy();
  expect(workspace.applyProposalToDraft).toHaveBeenCalledWith("rewrite-proposal");

  view.unmount();
  const secondWorkspace = makeWorkspace();
  api.requestTermRewrite.mockResolvedValue({ proposal: makeProposal(), external_provider_notice: "sent" });
  render(<TermLanguageCard body={body} workspace={secondWorkspace} navigate={vi.fn()} disabled={false} />);
  fireEvent.click(screen.getByRole("button", { name: "AI 重写", exact: true }));
  fireEvent.change(screen.getByLabelText("重写要求"), { target: { value: "Explain the mechanism." } });
  fireEvent.click(screen.getByRole("button", { name: "生成当前语言建议" }));
  fireEvent.click(await screen.findByRole("button", { name: "放弃建议" }));
  expect(await screen.findByText("建议已放弃；Term Draft 未被修改。")).toBeTruthy();
  expect(rejectProposal).toHaveBeenCalledWith("rewrite-proposal");
});
