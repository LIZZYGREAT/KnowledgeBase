import { useState } from "react";
import { requestResearchRewrite, updateResearchReview, type ResearchCandidate } from "./api";
import { MarkdownContent } from "./Markdown";
import { errorMessage } from "./errors";

export function ResearchCardReview({ candidate, values, onChange, onApprove, onReject, language, original }: { candidate: ResearchCandidate; values: Record<string, string>; onChange: (values: Record<string, string>) => void; onApprove: () => Promise<void>; onReject?: () => void; language: "zh" | "en"; original: Record<string, string> }) {
  const [editing, setEditing] = useState(false);
  const [revision, setRevision] = useState(candidate.review_revision ?? 0);
  const [field, setField] = useState("summary");
  const [requirements, setRequirements] = useState("");
  const [suggestion, setSuggestion] = useState<{ field: string; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const currentField = field + (language === "zh" ? "_zh" : "");
  async function save() {
    const candidate = await updateResearchReview(candidateId, values, revision);
    setRevision(candidate.review_revision ?? revision + 1);
  }
  const candidateId = candidate.id;
  async function approve() {
    setBusy(true); setError("");
    try { await save(); await onApprove(); }
    catch (reason) { setError(errorMessage(reason)); } finally { setBusy(false); }
  }
  async function rewrite() {
    setBusy(true); setError("");
    try { const result = await requestResearchRewrite(candidateId, currentField, values[currentField] ?? original[currentField] ?? "", requirements); setSuggestion({ field: currentField, text: result.text }); }
    catch (reason) { setError(errorMessage(reason)); } finally { setBusy(false); }
  }
  return <section aria-label="论文卡片审核" className="research-card-review">
    <button disabled={busy} onClick={() => void approve()}>通过</button><button disabled={busy} onClick={() => setEditing(!editing)}>编辑</button><button disabled={busy} onClick={() => { setEditing(true); }}>AI 重写</button>
    {onReject && <button disabled={busy} onClick={onReject}>拒绝</button>}
    {editing && <div><select disabled={busy} aria-label="编辑字段" value={field} onChange={(event) => setField(event.target.value)}><option value="summary">论文做了什么</option><option value="why_relevant">推荐理由</option><option value="reading_reason">阅读价值</option></select><label className="field-label">Markdown 源码<textarea disabled={busy} value={values[currentField] ?? original[currentField] ?? ""} onChange={(event) => onChange({ ...values, [currentField]: event.target.value })} /></label><MarkdownContent content={values[currentField] ?? original[currentField] ?? ""} /><button disabled={busy} onClick={() => { setBusy(true); void save().catch((reason) => setError(errorMessage(reason))).finally(() => setBusy(false)); }}>保存审核草稿</button><label className="field-label">重写要求<input disabled={busy} value={requirements} onChange={(event) => setRequirements(event.target.value)} /></label><p className="subtle-copy">显式生成时会把论文标题、摘要和原分析发送给 DeepSeek，生成结果只供预览。</p><button disabled={busy || !requirements.trim()} onClick={() => void rewrite()}>生成当前语言建议</button></div>}
    {suggestion && <section aria-label="重写对比"><p>原文 ↔ 新文</p><MarkdownContent content={values[suggestion.field] ?? original[suggestion.field] ?? ""} /><MarkdownContent content={suggestion.text} /><button disabled={busy} onClick={() => { onChange({ ...values, [suggestion.field]: suggestion.text }); setSuggestion(null); }}>采用</button><button disabled={busy} onClick={() => setSuggestion(null)}>放弃</button></section>}
    {error && <p role="alert" className="error-copy">{error}</p>}
  </section>;
}
