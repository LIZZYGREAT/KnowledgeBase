import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { WorkspaceMetadataDrawer } from "../../src/workspace/WorkspaceMetadataDrawer";

describe("Source metadata drawer", () => {
  it("edits Source identity fields as structured Draft metadata", () => {
    const onFrontmatterUpdate = vi.fn();
    const onSourcePdfChange = vi.fn();
    const onNavigate = vi.fn();
    render(<WorkspaceMetadataDrawer
      type="source"
      id="ewc-2017"
      canonicalSourceMetadata={{ attachments: { local_pdf: "storage://papers/ewc.pdf" } }}
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
      onSourcePdfChange={onSourcePdfChange}
      onNavigate={onNavigate}
      onClose={vi.fn()}
      onError={vi.fn()}
    />);

    expect(screen.getByRole("heading", { name: "来源信息" })).toBeTruthy();
    expect(screen.getByText("更改会自动保存")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "保存草稿" })).toBeNull();
    expect((screen.getByLabelText("Authors") as HTMLTextAreaElement).value).toBe("James Kirkpatrick");
    expect((screen.getByLabelText("DOI") as HTMLInputElement).value).toBe("10.1234/ewc");
    expect((screen.getByLabelText("arXiv ID") as HTMLInputElement).value).toBe("1701.00001");
    expect((screen.getByLabelText("OpenAlex ID") as HTMLInputElement).value).toBe("W111");
    expect(screen.getByText("已关联：ewc.pdf")).toBeTruthy();
    expect(screen.getByRole("link", { name: "打开 PDF" }).getAttribute("href")).toBe("/api/sources/ewc-2017/pdf");
    const advanced = document.querySelector("details.workspace-metadata-advanced") as HTMLDetailsElement;
    expect(advanced.open).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "通过 Review 检查" }));
    expect(onNavigate).toHaveBeenCalledWith("/review#imports");
    fireEvent.change(screen.getByLabelText("标题"), { target: { value: "Updated paper title" } });
    expect(onFrontmatterUpdate).toHaveBeenLastCalledWith("title", "Updated paper title");
    fireEvent.change(screen.getByLabelText("资料类型"), { target: { value: "book" } });
    expect(onFrontmatterUpdate).toHaveBeenLastCalledWith("type", "book");
    const authors = screen.getByLabelText("Authors");
    fireEvent.change(authors, { target: { value: "Ada Lovelace\nGrace Hopper\n" } });
    expect((authors as HTMLTextAreaElement).value).toBe("Ada Lovelace\nGrace Hopper\n");
    expect(onFrontmatterUpdate).toHaveBeenCalledWith("authors", ["Ada Lovelace", "Grace Hopper"]);
    fireEvent.blur(authors);
    expect(onFrontmatterUpdate).toHaveBeenLastCalledWith("authors", ["Ada Lovelace", "Grace Hopper"]);
    fireEvent.change(screen.getByLabelText("Year"), { target: { value: "2025" } });
    expect(onFrontmatterUpdate).toHaveBeenCalledWith("year", 2025);
    fireEvent.blur(screen.getByLabelText("Year"));
    expect(onFrontmatterUpdate).toHaveBeenLastCalledWith("year", 2025);
    fireEvent.change(screen.getByLabelText("DOI"), { target: { value: "10.1234/updated" } });
    expect(onFrontmatterUpdate).toHaveBeenLastCalledWith("identifiers", {
      doi: "10.1234/updated",
      arxiv_id: "1701.00001",
      openalex_id: "W111",
    });
    fireEvent.change(screen.getByLabelText("URL"), { target: { value: "https://example.org/updated" } });
    expect(onFrontmatterUpdate).toHaveBeenCalledWith("url", "https://example.org/updated");
    fireEvent.blur(screen.getByLabelText("URL"));
    expect(onFrontmatterUpdate).toHaveBeenLastCalledWith("url", "https://example.org/updated");
    fireEvent.click(screen.getByText("高级信息"));
    expect(advanced.open).toBe(true);
    fireEvent.change(screen.getByLabelText("Zotero Key"), { target: { value: "XYZ789" } });
    expect(onFrontmatterUpdate).toHaveBeenLastCalledWith("zotero_key", "XYZ789");

    const pdfAttachment = screen.getByLabelText("附件 URI");
    expect((pdfAttachment as HTMLInputElement).value).toBe("storage://papers/ewc.pdf");
    fireEvent.change(pdfAttachment, { target: { value: "not-a-storage-uri" } });
    expect(onSourcePdfChange).not.toHaveBeenCalled();
    fireEvent.blur(pdfAttachment);
    expect(onSourcePdfChange).not.toHaveBeenCalled();
    expect(screen.getByRole("alert").textContent).toContain("storage://");
    fireEvent.change(pdfAttachment, { target: { value: "storage://papers/updated.pdf" } });
    expect(onSourcePdfChange).toHaveBeenCalledWith("storage://papers/updated.pdf");
    fireEvent.keyDown(pdfAttachment, { key: "Enter" });
    expect(onSourcePdfChange).toHaveBeenCalledWith("storage://papers/updated.pdf");
    fireEvent.change(pdfAttachment, { target: { value: "" } });
    expect(onSourcePdfChange).toHaveBeenCalledWith("");
    fireEvent.blur(pdfAttachment);
    expect(onSourcePdfChange).toHaveBeenCalledWith("");
  });

  it("keeps the drawer open for invalid URL and persists valid Authors before Escape closes", () => {
    const onFrontmatterUpdate = vi.fn();
    const onClose = vi.fn();
    render(<WorkspaceMetadataDrawer
      type="source"
      id="ewc-2017"
      content={["schema_version: 1", "id: ewc-2017", "type: paper", "title: Paper", "authors: []", "identifiers: {}", "attachments: {}"].join("\n")}
      sourceEntries={[]}
      sourceError=""
      canonicalEvidenceCount={0}
      onFrontmatterUpdate={onFrontmatterUpdate}
      onFrontmatterListUpdate={vi.fn()}
      onSourcePdfChange={vi.fn()}
      onNavigate={vi.fn()}
      onClose={onClose}
      onError={vi.fn()}
    />);

    const authors = screen.getByLabelText("Authors");
    fireEvent.focus(authors);
    fireEvent.change(authors, { target: { value: "Ada Lovelace\n" } });
    expect(onFrontmatterUpdate).toHaveBeenCalledWith("authors", ["Ada Lovelace"]);
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledOnce();

    onClose.mockClear();
    const url = screen.getByLabelText("URL");
    fireEvent.focus(url);
    fireEvent.change(url, { target: { value: "ftp://example.org/paper" } });
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByText("URL 须为空，或使用有效的 http:// / https:// 地址。")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "保存草稿" })).toBeNull();
  });

  it("resets buffered fields when the drawer switches to another Source", () => {
    const props = {
      type: "source" as const,
      sourceEntries: [],
      sourceError: "",
      canonicalEvidenceCount: 0,
      onFrontmatterUpdate: vi.fn(),
      onFrontmatterListUpdate: vi.fn(),
      onSourcePdfChange: vi.fn(),
      onNavigate: vi.fn(),
      onClose: vi.fn(),
      onError: vi.fn(),
    };
    const { rerender } = render(<WorkspaceMetadataDrawer
      {...props}
      id="ewc-2017"
      content={["schema_version: 1", "id: ewc-2017", "type: paper", "title: First", "identifiers: {}", "attachments: {}"].join("\n")}
    />);
    const url = screen.getByLabelText("URL");
    fireEvent.focus(url);
    fireEvent.change(url, { target: { value: "ftp://invalid.example" } });
    expect((url as HTMLInputElement).value).toBe("ftp://invalid.example");

    rerender(<WorkspaceMetadataDrawer
      {...props}
      id="next-paper"
      content={["schema_version: 1", "id: next-paper", "type: paper", "title: Second", "url: https://example.org/next", "identifiers: {}", "attachments: {}"].join("\n")}
    />);

    expect((screen.getByLabelText("URL") as HTMLInputElement).value).toBe("https://example.org/next");
    expect(screen.queryByText("URL 须为空，或使用有效的 http:// / https:// 地址。")).toBeNull();
  });

  it("routes an unlinked Source to Review to add a PDF", () => {
    const onNavigate = vi.fn();
    render(<WorkspaceMetadataDrawer
      type="source"
      id="ewc-2017"
      content={["schema_version: 1", "id: ewc-2017", "type: paper", "title: Paper", "attachments: {}"].join("\n")}
      sourceEntries={[]}
      sourceError=""
      canonicalEvidenceCount={0}
      onFrontmatterUpdate={vi.fn()}
      onFrontmatterListUpdate={vi.fn()}
      onSourcePdfChange={vi.fn()}
      onNavigate={onNavigate}
      onClose={vi.fn()}
      onError={vi.fn()}
    />);

    expect(screen.getByText("尚未关联 PDF")).toBeTruthy();
    const advanced = document.querySelector("details.workspace-metadata-advanced") as HTMLDetailsElement;
    expect(advanced.open).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "通过 Review 添加 PDF" }));
    expect(onNavigate).toHaveBeenCalledWith("/review#imports");
    fireEvent.click(screen.getByText("高级信息"));
    expect((screen.getByLabelText("附件 URI") as HTMLInputElement).value).toBe("");
  });

  it("does not offer a PDF URL that exists only in an unpublished Draft", () => {
    render(<WorkspaceMetadataDrawer
      type="source"
      id="ewc-2017"
      content={["schema_version: 1", "id: ewc-2017", "type: paper", "title: Paper", "attachments:", "  local_pdf: storage://papers/ewc.pdf"].join("\n")}
      canonicalSourceMetadata={{ attachments: {} }}
      sourceEntries={[]}
      sourceError=""
      canonicalEvidenceCount={0}
      onFrontmatterUpdate={vi.fn()}
      onFrontmatterListUpdate={vi.fn()}
      onSourcePdfChange={vi.fn()}
      onNavigate={vi.fn()}
      onClose={vi.fn()}
      onError={vi.fn()}
    />);

    expect(screen.getByText("已关联：ewc.pdf")).toBeTruthy();
    expect(screen.getByText("发布后可在这里打开 PDF。")).toBeTruthy();
    expect(screen.queryByRole("link", { name: "打开 PDF" })).toBeNull();
  });
});
