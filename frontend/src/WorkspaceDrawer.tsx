import { useEffect, type ReactNode } from "react";

export function WorkspaceDrawer({
  title,
  description,
  onClose,
  children,
  wide = false,
}: {
  title: string;
  description: string;
  onClose: () => void;
  children: ReactNode;
  wide?: boolean;
}) {
  useEffect(() => {
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [onClose]);

  return <div className="workspace-drawer-overlay" onMouseDown={(event) => {
    if (event.target === event.currentTarget) onClose();
  }}>
    <aside className={`workspace-drawer${wide ? " wide" : ""}`} role="dialog" aria-modal="true" aria-label={title}>
      <header className="workspace-drawer-header">
        <div><p className="eyebrow">WORKSPACE</p><h2>{title}</h2><p>{description}</p></div>
        <button className="workspace-drawer-close" type="button" aria-label="关闭抽屉" onClick={onClose}>×</button>
      </header>
      <div className="workspace-drawer-body">{children}</div>
    </aside>
  </div>;
}
