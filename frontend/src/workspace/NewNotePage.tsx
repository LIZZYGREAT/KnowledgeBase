import { useState, type FormEvent } from "react";
import { createBlankDocument } from "../api";
import { PageHeader } from "../ui";
import { entityWorkspaceUrl } from "../workspaceRoute";

export function NewNotePage({ navigate }: { navigate: (path: string) => void }) {
  const [title, setTitle] = useState("");
  const [documentType, setDocumentType] = useState<"paper-note" | "learning-note" | "course-note">("learning-note");
  const [error, setError] = useState("");
  const [creating, setCreating] = useState(false);

  async function createNote(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setCreating(true);
    setError("");
    try {
      const draft = await createBlankDocument(title.trim(), documentType);
      navigate(entityWorkspaceUrl("document", draft.entity_id));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "发生未知错误。");
    } finally {
      setCreating(false);
    }
  }

  return <div className="page-stack new-note-page">
      <PageHeader eyebrow="NEW KNOWLEDGE" title="新建笔记" description="先创建一个运行时 Draft，再在阅读工作区中补充内容并发布。" />
    <form className="surface new-note-form" onSubmit={(event) => void createNote(event)}>
      <label className="field-label">标题<input autoFocus required maxLength={240} value={title} onChange={(event) => setTitle(event.target.value)} placeholder="例如：图神经网络的阅读笔记" /></label>
      <label className="field-label">笔记类型<select value={documentType} onChange={(event) => setDocumentType(event.target.value as typeof documentType)}><option value="learning-note">Learning Note</option><option value="paper-note">Paper Note</option><option value="course-note">Course Note</option></select></label>
      {error && <p className="error-copy" role="alert">{error}</p>}
      <div className="editor-main-actions"><button className="button button-secondary" type="button" onClick={() => navigate("/")}>取消</button><button className="button button-primary" type="submit" disabled={creating || !title.trim()}>{creating ? "正在创建…" : "开始编辑"}</button></div>
    </form>
  </div>;
}
