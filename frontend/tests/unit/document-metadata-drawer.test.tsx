import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { WorkspaceMetadataDrawer } from "../../src/workspace/WorkspaceMetadataDrawer";

describe("Document metadata drawer", () => {
  it("syncs normalized taxonomy lists while retaining raw input and closes by backdrop", () => {
    const onFrontmatterListUpdate = vi.fn();
    const onFrontmatterUpdate = vi.fn();
    const onClose = vi.fn();
    render(<WorkspaceMetadataDrawer
      type="document"
      id="continual-learning"
      content={[
        "---",
        "schema_version: 1",
        "id: continual-learning",
        "title: Continual Learning",
        "domains:",
        "  - artificial-intelligence",
        "topics:",
        "  - machine-learning",
        "tags:",
        "  - overview",
        "sources:",
        "  - source-1",
        "---",
        "# Continual Learning",
      ].join("\n")}
      sourceEntries={[{ id: "source-1", title: "Source One", entity_type: "source", metadata: {} }]}
      sourceError=""
      canonicalEvidenceCount={0}
      onFrontmatterUpdate={onFrontmatterUpdate}
      onFrontmatterListUpdate={onFrontmatterListUpdate}
      onSourcePdfChange={vi.fn()}
      onSave={vi.fn()}
      onClose={onClose}
      onError={vi.fn()}
    />);

    const domains = screen.getByLabelText("Domains") as HTMLInputElement;
    const topics = screen.getByLabelText("Topics") as HTMLInputElement;
    const tags = screen.getByLabelText("Tags") as HTMLInputElement;
    expect(domains.value).toBe("artificial-intelligence");
    expect(topics.value).toBe("machine-learning");
    expect(tags.value).toBe("overview");
    expect((screen.getByRole("checkbox", { name: /Source One/ }) as HTMLInputElement).checked).toBe(true);

    fireEvent.focus(domains);
    fireEvent.change(domains, { target: { value: "artificial-intelligence," } });
    expect(domains.value).toBe("artificial-intelligence,");
    fireEvent.change(domains, { target: { value: "artificial-intelligence, deep-learning" } });
    expect(onFrontmatterListUpdate).toHaveBeenNthCalledWith(1, "domains", "artificial-intelligence");
    expect(onFrontmatterListUpdate).toHaveBeenLastCalledWith("domains", "artificial-intelligence, deep-learning");

    fireEvent.focus(topics);
    fireEvent.change(topics, { target: { value: "machine-learning, representation-learning" } });
    expect(onFrontmatterListUpdate).toHaveBeenLastCalledWith("topics", "machine-learning, representation-learning");

    fireEvent.focus(tags);
    fireEvent.change(tags, { target: { value: "overview, survey" } });
    expect(onFrontmatterListUpdate).toHaveBeenLastCalledWith("tags", "overview, survey");

    fireEvent.mouseDown(document.querySelector(".workspace-drawer-overlay")!);
    expect(onClose).toHaveBeenCalledOnce();
  });
});
