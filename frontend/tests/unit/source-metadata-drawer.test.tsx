import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { WorkspaceMetadataDrawer } from "../../src/workspace/WorkspaceMetadataDrawer";

describe("Source metadata drawer", () => {
  it("edits Source identity fields as structured Draft metadata", () => {
    const onFrontmatterUpdate = vi.fn();
    render(<WorkspaceMetadataDrawer
      type="source"
      id="ewc-2017"
      content={[
        "schema_version: 1",
        "id: ewc-2017",
        "type: paper",
        "title: Elastic Weight Consolidation",
        "authors:",
        "  - James Kirkpatrick",
        "year: 2017",
        "identifiers:",
        "  doi: 10.1234/ewc",
        '  arxiv_id: "1701.00001"',
        "  openalex_id: W111",
        "url: https://example.org/paper",
        "zotero_key: ABC123",
        "attachments:",
        "  local_pdf: storage://papers/ewc.pdf",
      ].join("\n")}
      sourceEntries={[]}
      sourceError=""
      canonicalEvidenceCount={0}
      onFrontmatterUpdate={onFrontmatterUpdate}
      onFrontmatterListUpdate={vi.fn()}
      onSourcePdfChange={vi.fn()}
      onSave={vi.fn()}
      onClose={vi.fn()}
      onError={vi.fn()}
    />);

    expect(screen.getByRole("heading", { name: "Source metadata" })).toBeTruthy();
    expect((screen.getByLabelText("Authors") as HTMLTextAreaElement).value).toBe("James Kirkpatrick");
    expect((screen.getByLabelText("DOI") as HTMLInputElement).value).toBe("10.1234/ewc");
    expect((screen.getByLabelText("arXiv ID") as HTMLInputElement).value).toBe("1701.00001");
    expect((screen.getByLabelText("OpenAlex ID") as HTMLInputElement).value).toBe("W111");
    expect((screen.getByLabelText("附件 URI") as HTMLInputElement).value).toBe("storage://papers/ewc.pdf");
    fireEvent.change(screen.getByLabelText("标题"), { target: { value: "Updated paper title" } });
    expect(onFrontmatterUpdate).toHaveBeenLastCalledWith("title", "Updated paper title");
    fireEvent.change(screen.getByLabelText("Type"), { target: { value: "book" } });
    expect(onFrontmatterUpdate).toHaveBeenLastCalledWith("type", "book");
    fireEvent.change(screen.getByLabelText("Authors"), { target: { value: "Ada Lovelace\nGrace Hopper" } });
    expect(onFrontmatterUpdate).toHaveBeenLastCalledWith("authors", ["Ada Lovelace", "Grace Hopper"]);
    fireEvent.change(screen.getByLabelText("Year"), { target: { value: "2025" } });
    expect(onFrontmatterUpdate).not.toHaveBeenCalledWith("year", 2025);
    fireEvent.blur(screen.getByLabelText("Year"));
    expect(onFrontmatterUpdate).toHaveBeenLastCalledWith("year", 2025);
    fireEvent.change(screen.getByLabelText("DOI"), { target: { value: "10.1234/updated" } });
    expect(onFrontmatterUpdate).toHaveBeenLastCalledWith("identifiers", {
      doi: "10.1234/updated",
      arxiv_id: "1701.00001",
      openalex_id: "W111",
    });
    fireEvent.change(screen.getByLabelText("URL"), { target: { value: "https://example.org/updated" } });
    expect(onFrontmatterUpdate).not.toHaveBeenCalledWith("url", "https://example.org/updated");
    fireEvent.blur(screen.getByLabelText("URL"));
    expect(onFrontmatterUpdate).toHaveBeenLastCalledWith("url", "https://example.org/updated");
    fireEvent.click(screen.getByText("Advanced"));
    fireEvent.change(screen.getByLabelText("Zotero Key"), { target: { value: "XYZ789" } });
    expect(onFrontmatterUpdate).toHaveBeenLastCalledWith("zotero_key", "XYZ789");
  });
});
