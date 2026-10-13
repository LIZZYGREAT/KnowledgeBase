import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ResearchManualStatus } from "../../src/ResearchManualStatus";
import { listManualResearchRequests } from "../../src/api";
vi.mock("../../src/api", () => ({ listManualResearchRequests: vi.fn() }));
afterEach(() => vi.resetAllMocks());

it("restores a persisted request and displays actual results without guessing progress", async () => {
  const record = { request: { id: "request", status: "pending" as const, created_at: "2026-10-13T10:00:00Z", claimed_at: null }, run: null };
  vi.mocked(listManualResearchRequests).mockResolvedValue([record]);
  const complete = vi.fn();
  const results = vi.fn();
  const view = render(<ResearchManualStatus profileId="profile" refreshKey={0} aiEnabled={false} onComplete={complete} onResults={results} />);
  await screen.findByText("等待执行");
  expect(complete).not.toHaveBeenCalled();
  vi.mocked(listManualResearchRequests).mockResolvedValue([{ ...record, request: { ...record.request, status: "completed" }, run: { id: "run", status: "success", fetched_count: 4, new_work_count: 2, analyzed_count: 0, surfaced_count: 0 } as never }]);
  fireEvent.click(screen.getByText("刷新状态"));
  await screen.findByText("检索已完成");
  expect(screen.getByText(/检查 4 篇，新增 2 篇/)).toBeTruthy();
  expect(screen.getByText(/AI 分析已关闭/)).toBeTruthy();
  fireEvent.click(screen.getByText("查看新论文"));
  expect(results).toHaveBeenCalledOnce();
  await waitFor(() => expect(listManualResearchRequests).toHaveBeenCalledTimes(2));
  view.unmount();
});

it("shows a failed request as failure even without a run record", async () => {
  vi.mocked(listManualResearchRequests).mockResolvedValue([{ request: { id: "failed", status: "failed", created_at: "2026-10-13T10:00:00Z", claimed_at: null }, run: null }]);
  render(<ResearchManualStatus profileId="profile" refreshKey={0} aiEnabled onComplete={() => undefined} />);
  await screen.findByText("检索失败");
  expect(screen.getByText(/执行前检查失败/)).toBeTruthy();
  expect(listManualResearchRequests).toHaveBeenCalledTimes(1);
});
