import type { EntityType } from "../api";
import { MarkdownBlockEditor } from "../MarkdownBlockEditor";
import { SectionHeading } from "../ui";

export function WorkspaceBodyEditor({ type, content, isDirty, onChange, onSelectionChange, onSave, onNavigate }: {
  type: EntityType;
  content: string;
  isDirty: boolean;
  onChange: (value: string) => void;
  onSelectionChange: (value: string) => void;
  onSave: () => void;
  onNavigate: (path: string) => void;
}) {
  if (type !== "source") return <section className="surface markdown-block-editor-panel">
    <MarkdownBlockEditor content={content} onChange={onChange} onSelectionChange={onSelectionChange} onBlur={() => { if (isDirty) onSave(); }} onNavigate={onNavigate} />
  </section>;

  return <div className="editor-grid">
    <section className="surface editor-writing-panel">
      <SectionHeading title="Source YAML" detail="第一次修改后自动创建 Draft · 650ms 后保存" />
      <textarea className="knowledge-editor" value={content} onChange={(event) => onChange(event.target.value)} onBlur={() => { if (isDirty) onSave(); }} spellCheck={false} aria-label="Source YAML Draft" />
    </section>
    <section className="surface editor-preview-panel">
      <SectionHeading title="YAML 预览" detail="完整 Source 元数据" />
      <pre className="source-yaml-preview">{content}</pre>
    </section>
  </div>;
}
