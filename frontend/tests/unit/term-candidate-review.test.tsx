import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import { TermCandidateReview } from "../../src/pages/TermCandidateReview";
import { preflightDraft, publishDraft, type Draft, type TermCandidate } from "../../src/api";

const state = vi.hoisted(() => ({ content: "---\nschema_version: 1\nid: replay\ntitle: Replay\ntype: concept\ndepth: stub\n---\n# Replay\n\nExperience Replay retains examples.\n" }));
vi.mock("../../src/api", () => ({ applyProposalToDraft: vi.fn(), discardDraft: vi.fn(), listProposals: vi.fn().mockResolvedValue([]), preflightDraft: vi.fn(), publishDraft: vi.fn(), rejectTermCandidate: vi.fn(), requestCandidateTermDraftProposal: vi.fn(), requestTermRewrite: vi.fn() }));
vi.mock("../../src/reader/readerModel", () => ({ hashText: vi.fn().mockResolvedValue("hash") }));
vi.mock("../../src/draft/useRuntimeDraftSession", () => ({ useRuntimeDraftSession: () => ({ content: state.content, loading: false, state: "saved", error: "", getCurrentContent: () => state.content, updateContent: (value: string) => { state.content = value; }, saveNow: async () => ({ id: "d", revision: 2, content: state.content }) }) }));

beforeEach(() => {
  vi.mocked(preflightDraft).mockResolvedValue({ draft_id: "d", valid: true, conflict: false, errors: [], warnings: [] });
});

test("one approval marks human review, preflights and publishes the reviewed revision", async () => {
  const done = vi.fn();
  vi.mocked(publishDraft).mockResolvedValue({ draft_id: "d", entity_id: "replay", entity_type: "term", commit_revision: "commit", warnings: [] });
  render(<TermCandidateReview candidate={{ id: "c", display_name: "Replay" } as TermCandidate} seed={{ id: "d", entity_id: "replay", content: state.content } as Draft} onDone={done} />);
  fireEvent.click(screen.getByRole("button", { name: "通过", exact: true }));
  await waitFor(() => expect(done).toHaveBeenCalled());
  expect(state.content).toContain("status: approved");
  expect(preflightDraft).toHaveBeenCalledWith("d");
  expect(publishDraft).toHaveBeenCalledWith("d", 2);
});

test("a publish conflict keeps the reviewed Draft and never reports approval", async () => {
  const done = vi.fn();
  vi.mocked(publishDraft).mockRejectedValue(new Error("正式版已变化"));
  render(<TermCandidateReview candidate={{ id: "c", display_name: "Replay" } as TermCandidate} seed={{ id: "d", entity_id: "replay", content: state.content } as Draft} onDone={done} />);
  fireEvent.click(screen.getByRole("button", { name: "通过", exact: true }));
  await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("正式版已变化"));
  expect(done).not.toHaveBeenCalled();
  expect(state.content).toContain("Experience Replay retains examples.");
});
