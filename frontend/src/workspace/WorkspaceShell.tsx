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
  const [explorerOpen, setExplorerOpen] = useState(() => !isNarrowViewport());
  const previousId = useRef(id);

  useEffect(() => {
    if (previousId.current !== id && isNarrowViewport()) setExplorerOpen(false);
    previousId.current = id;
  }, [id]);

  return <section className={`workspace-shell ${explorerOpen ? "explorer-open" : "explorer-closed"}`} aria-label={`${entityLabels[type]}工作区`} data-entity-id={id}>
    <div className="workspace-shell-toolbar">
      <button className="button button-secondary workspace-explorer-toggle" type="button" aria-controls="workspace-explorer-pane" aria-expanded={explorerOpen} onClick={() => setExplorerOpen((open) => !open)}>
        {explorerOpen ? "隐藏 Explorer" : "显示 Explorer"}
      </button>
      <span>{entityLabels[type]}工作区</span>
    </div>
    {explorerOpen && <button className="workspace-explorer-scrim" type="button" aria-label="关闭 Explorer" onClick={() => setExplorerOpen(false)} />}
    <div className="workspace-workspace-layout">
      <aside className={`workspace-explorer-pane ${explorerOpen ? "" : "is-hidden"}`} id="workspace-explorer-pane" aria-label="Knowledge Explorer" aria-hidden={!explorerOpen}>{explorer}</aside>
      <main className="workspace-document-pane">{children}</main>
    </div>
  </section>;
}
