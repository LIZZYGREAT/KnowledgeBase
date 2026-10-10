import { parse } from "yaml";
import type { Draft } from "./api";

export function ResearchSourceReview({ draft, busy, error, onConfirm, onEdit }: {
  draft: Draft;
  busy: boolean;
  error: string;
  onConfirm: () => void;
  onEdit: () => void;
}) {
  let metadata: Record<string, unknown> = {};
  let parseError = "";
  try {
    const value: unknown = parse(draft.content);
    if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error();
    metadata = value as Record<string, unknown>;
  } catch {
    parseError = "无法读取来源信息，请返回编辑修正草稿。";
  }
  return <div className="explorer-modal-backdrop"><section className="explorer-modal surface" role="dialog" aria-modal="true" aria-label="确认已有 Source Draft">
    <h2>Source 草稿审核</h2><p>检查已有修改；确认后将通过正常发布流程收藏此来源。</p>
    {parseError ? <p role="alert">{parseError}</p> : <dl className="source-fields">
      <div><dt>标题</dt><dd>{text(metadata.title)}</dd></div>
      <div><dt>资料类型</dt><dd>{text(metadata.type)}</dd></div>
      <div><dt>作者</dt><dd>{text(metadata.authors)}</dd></div>
      <div><dt>年份</dt><dd>{text(metadata.year)}</dd></div>
      <div><dt>刊物</dt><dd>{text(metadata.venue)}</dd></div>
      <div><dt>网址</dt><dd>{text(metadata.url)}</dd></div>
      {Object.entries(metadata.identifiers as Record<string, unknown> ?? {}).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{text(value)}</dd></div>)}
      <div><dt>附件</dt><dd>{text(metadata.attachments)}</dd></div>
      <div><dt>元数据审核</dt><dd>{text(metadata.metadata_review)}</dd></div>
    </dl>}
    <details><summary>查看完整 YAML</summary><pre>{draft.content}</pre></details>
    {error && <p role="alert">{error}</p>}
    <button disabled={busy || Boolean(parseError)} onClick={onConfirm}>确认通过并发布 Source</button>
    <button disabled={busy} onClick={onEdit}>返回编辑</button>
  </section></div>;
}

function text(value: unknown): string {
  if (value == null || value === "") return "未填写";
  if (Array.isArray(value)) return value.map(text).join("、");
  if (typeof value === "object") return Object.entries(value).map(([key, item]) => `${key}: ${text(item)}`).join("；");
  return String(value);
}
