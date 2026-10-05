import { render, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as api from "../../src/api";
import { ReviewPage } from "../../src/pages/ReviewPage";

describe("Review page navigation", () => {
  afterEach(() => {
    window.history.replaceState({}, "", "/");
    vi.restoreAllMocks();
  });

  it("scrolls to Import Review after the page resource has rendered", async () => {
    window.history.replaceState({}, "", "/review#imports");
    vi.spyOn(api, "listAllEntities").mockResolvedValue([]);
    vi.spyOn(api, "listProposals").mockResolvedValue([]);
    vi.spyOn(api, "listImports").mockResolvedValue([]);
    vi.spyOn(api, "listLinkIssues").mockResolvedValue([]);
    vi.spyOn(api, "listStalePresentationAnnotations").mockResolvedValue([]);
    const scrollIntoView = vi.spyOn(HTMLElement.prototype, "scrollIntoView").mockImplementation(() => undefined);

    const { container } = render(<ReviewPage onOpen={vi.fn()} navigate={vi.fn()} />);

    await waitFor(() => expect(scrollIntoView).toHaveBeenCalledWith({ block: "start" }));
    expect(container.querySelector("#imports")).not.toBeNull();
  });
});
