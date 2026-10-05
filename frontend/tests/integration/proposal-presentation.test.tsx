import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import type { Proposal } from "../../src/api";
import { WorkspaceProposalPresentation } from "../../src/workspace/WorkspaceProposalPresentation";

function proposal(kind: string, result: Record<string, unknown>): Proposal {
  return {
    id: "proposal-1",
    target_type: "document",
    target_id: "quick-start",
    kind,
    status: "proposed",
    base_content_hash: "sha256:test",
    payload: { result },
    diff_text: null,
    created_by: "ai",
    provider: "deepseek",
    model: "deepseek-chat",
    created_at: "2026-10-05T00:00:00+00:00",
    reviewed_at: null,
    review_note: null,
  };
}

it("renders review Markdown for people and keeps raw JSON collapsed", async () => {
  const { container } = render(<WorkspaceProposalPresentation proposal={proposal("document_revision", {
    summary: "## Review\n\n- **Clear** structure.",
    findings: [{ topic: "Navigation", explanation: "The control is easy to find.", suggestion: "Keep **Focus** visible.", severity: "suggestion" }],
  })} />);

  expect(await screen.findByRole("heading", { name: "Review", level: 2 }, { timeout: 8000 })).toBeTruthy();
  expect(screen.getByText("Clear", { selector: "strong" })).toBeTruthy();
  expect(screen.getByText("Focus", { selector: "strong" })).toBeTruthy();
  const raw = container.querySelector(".proposal-raw-data");
  expect(raw instanceof HTMLDetailsElement && raw.open).toBe(false);
  expect(container.querySelector(".proposal-human-view > .proposal-payload")).toBeNull();
});

it("presents metadata fields as labels and values instead of serialized objects", async () => {
  render(<WorkspaceProposalPresentation proposal={proposal("metadata", {
    changes: { title: "A clearer title", topics: ["human-computer-interaction"] },
    rationale: "The title can better describe **the topic**.",
  })} />);

  expect(await screen.findByText("the topic", { selector: "strong" })).toBeTruthy();
  expect(screen.getByText("Title")).toBeTruthy();
  expect(screen.getByText("Topics")).toBeTruthy();
  expect(screen.getByText("A clearer title")).toBeTruthy();
});

it("renders a Term definition and an Evidence claim as Markdown", async () => {
  const term = render(<WorkspaceProposalPresentation proposal={proposal("new_term", {
    id: "new-concept", title: "New concept", type: "concept", depth: "standard", aliases: ["Alias"], definition: "A **useful** definition.",
  })} />);
  expect(await screen.findByText("useful", { selector: "strong" })).toBeTruthy();
  term.unmount();

  render(<WorkspaceProposalPresentation proposal={proposal("evidence", {
    candidates: [{ source_id: "source-1", claim: "A claim with **support**.", rationale: "The Source discusses this result." }],
  })} />);
  expect(await screen.findByText("support", { selector: "strong" })).toBeTruthy();
  expect(screen.getByText("Source · source-1")).toBeTruthy();
});
