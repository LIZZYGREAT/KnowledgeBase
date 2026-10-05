import { useEffect, useRef, useState, type ReactNode } from "react";
import type { EntityType } from "../api";

const entityLabels: Record<EntityType, string> = {
  document: "文档",
  term: "术语",
  source: "来源",
};

function isNarrowViewport() {
  return typeof window !== "undefined"
    && typeof window.matchMedia === "function"
    && window.matchMedia("(max-width: 980px)").matches;
}

export function WorkspaceShell({
  type,
  id,
  explorer,
  children,
}: {
  type: EntityType;
  id: string;
  explorer: ReactNode;
  children: ReactNode;
}) {
  const [explorerOpen, setExplorerOpen] = useState(false);
  const previousId = useRef(id);

  useEffect(() => {
    if (previousId.current !== id && isNarrowViewport()) setExplorerOpen(false);
    previousId.current = id;
  }, [id]);

  useEffect(() => {
    if (!explorerOpen) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setExplorerOpen(false);
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [explorerOpen]);

  return <section className="workspace-shell" aria-label={`${entityLabels[type]}工作区`} data-entity-id={id}>
    <button className="button button-secondary workspace-explorer-toggle" type="button" aria-controls="workspace-explorer-pane" aria-expanded={explorerOpen} aria-label={explorerOpen ? "关闭 Knowledge Explorer" : "打开 Knowledge Explorer"} onClick={() => setExplorerOpen((open) => !open)}>
      <span aria-hidden="true">⌘</span> Explorer
    </button>
    {explorerOpen && <button className="workspace-explorer-scrim" type="button" aria-label="关闭 Explorer" onClick={() => setExplorerOpen(false)} />}
    {explorerOpen && <aside className="workspace-explorer-pane" id="workspace-explorer-pane" aria-label="Knowledge Explorer">{explorer}</aside>}
    <main className="workspace-document-pane">{children}</main>
  </section>;
}
