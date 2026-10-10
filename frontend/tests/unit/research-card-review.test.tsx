import { useState } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { ResearchCardReview } from "../../src/ResearchCardReview";
import { requestResearchRewrite, updateResearchReview, type ResearchCandidate } from "../../src/api";

vi.mock("../../src/api", () => ({ requestResearchRewrite: vi.fn(), updateResearchReview: vi.fn() }));

test("failed saves retain edits and do not approve or call AI", async () => {
  vi.mocked(updateResearchReview).mockRejectedValue(new Error("保存冲突"));
  const approve = vi.fn();
  function Card() {
    const [values, setValues] = useState<Record<string, string>>({});
    return <ResearchCardReview candidate={{ id: "c", review_revision: 0 } as ResearchCandidate} values={values} onChange={setValues} onApprove={approve} language="zh" original={{ summary_zh: "原始简介" }} />;
  }
  render(<Card />);
  fireEvent.click(screen.getByRole("button", { name: "编辑", exact: true }));
  fireEvent.change(screen.getByLabelText("Markdown 源码"), { target: { value: "用户修改" } });
  fireEvent.click(screen.getByRole("button", { name: "通过", exact: true }));
  await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("保存冲突"));
  expect((screen.getByLabelText("Markdown 源码") as HTMLTextAreaElement).value).toBe("用户修改");
  expect(updateResearchReview).toHaveBeenCalledWith("c", { summary_zh: "用户修改" }, 0);
  expect(approve).not.toHaveBeenCalled();
  expect(requestResearchRewrite).not.toHaveBeenCalled();
});
