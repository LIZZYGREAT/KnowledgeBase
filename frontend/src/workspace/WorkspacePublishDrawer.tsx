import { useState } from "react";
import type { PublishReviewItem } from "../publishReview.js";
import { createLineDiff, summarizePublishChanges } from "../publishReview.js";
import { WorkspaceDrawer } from "../WorkspaceDrawer";

export function WorkspacePublishDrawer({
  items,
  busy,
  publishing,
  published,
  error,
  batch,
  onClose,
  onRefresh,
  onPublish,
}: {
  items: PublishReviewItem[];
  busy: boolean;
  publishing: boolean;
  published: boolean;
  error: string;
  batch: boolean;
  onClose: () => void;
  onRefresh: () => void;
  onPublish: () => void;
}) {
  const [showDiff, setShowDiff] = useState(false);
  const summary = summarizePublishChanges(items);
  const checksComplete = items.length > 0 && items.every((item) => !item.preflight.conflict && item.preflight.valid && !item.comparison.canonical_changed);
  const warnings = items.flatMap((item) => item.preflight.warnings.map((warning) => ({ label: item.label, warning })));
  const errors = items.flatMap((item) => item.preflight.errors.map((message) => ({ label: item.label, message })));

  return <WorkspaceDrawer
    title="发布变更"
    description={batch ? "检查 Document 与 Collection 的 Draft，再由 Publisher 在一次 Git 提交中发布。" : "检查 Draft 与当前正式内容的差异，再由 Publisher 完成发布。"}
    wide
    onClose={onClose}
  >
    <section className="drawer-section workspace-publish-review">
      <section className="publish-review-section" aria-labelledby="publish-summary-heading">
        <h3 id="publish-summary-heading">变更摘要</h3>
        <ul className="publish-summary-list">
          <li>Markdown 区块变化：{summary.changedBlockCount}</li>
          <li>元数据变化：{summary.metadataByTarget.length
            ? summary.metadataByTarget.map((item) => `${item.label}：${item.fields.join("、")}`).join("；")
            : "无"}</li>
          {summary.collectionUpdated && <li>Collection 已更新</li>}
        </ul>
      </section>

      <section className="publish-review-section" aria-labelledby="publish-validation-heading">
        <h3 id="publish-validation-heading">校验</h3>
        {busy && <p className="subtle-copy" role="status">正在保存 Draft 并检查 Canonical…</p>}
        {items.length > 0 && <ul className="publish-validation-list">
          {items.map((item) => <li key={item.comparison.draft.id}>
            <span>{item.label} · Publisher 预检（结构、Markdown 与引用）</span>
            <strong className={item.preflight.valid ? "publish-check-pass" : "publish-check-fail"}>{item.preflight.valid ? "通过" : "未通过"}</strong>
          </li>)}
          <li>
            <span>Canonical 冲突</span>
            <strong className={checksComplete ? "publish-check-pass" : "publish-check-fail"}>{checksComplete ? "未发现" : items.some((item) => item.preflight.conflict || item.comparison.canonical_changed) ? "需要处理" : "尚未通过"}</strong>
          </li>
        </ul>}
        {errors.length > 0 && <ul className="preflight-errors">{errors.map(({ label, message }, index) => <li key={`${label}:${index}`}>{label}：{message}</li>)}</ul>}
        {warnings.length > 0 && <div className="preflight-warnings"><strong>发布警告</strong><ul>{warnings.map(({ label, warning }, index) => <li key={`${label}:${index}`}>{label}：{warning}</li>)}</ul></div>}
        {!busy && items.length === 0 && <p className="subtle-copy">尚未完成检查。</p>}
      </section>

      <section className="publish-review-section" aria-labelledby="publish-diff-heading">
        <div className="publish-review-heading-row"><h3 id="publish-diff-heading">差异</h3><button className="button button-secondary" type="button" disabled={busy || !items.length} aria-expanded={showDiff} onClick={() => setShowDiff((value) => !value)}>{showDiff ? "收起完整差异" : "查看完整差异"}</button></div>
        {!showDiff && <p className="subtle-copy">差异对比 Draft 与当前 Canonical 内容。</p>}
        {showDiff && items.map((item) => <section className="publish-diff-target" key={item.comparison.draft.id}>
          <h4>{item.label}</h4>
          <pre className="publish-full-diff">{createLineDiff(item.comparison.current_content, item.comparison.draft.content).map((line, index) => <span className={`publish-diff-line ${line.kind}`} key={`${line.kind}:${index}`}><span aria-hidden="true">{line.kind === "added" ? "+" : line.kind === "removed" ? "−" : " "}</span>{line.text || " "}{"\n"}</span>)}</pre>
        </section>)}
      </section>

      {error && <p className="error-copy" role="alert">{error}</p>}
      <p className="trust-note">检查不会写入 Canonical。发布前 Publisher 会再次校验引用与冲突；成功后服务端更新正文和索引。</p>
      <div className="drawer-footer">
        <button className="button button-secondary" type="button" disabled={busy || publishing} onClick={onClose}>取消</button>
        <button className="button button-secondary" type="button" disabled={busy || publishing} onClick={onRefresh}>重新检查</button>
        <button className="button button-primary" type="button" disabled={busy || publishing || !checksComplete || published} onClick={onPublish}>{publishing ? "发布中…" : batch ? "Publish All · 一个 Git 提交" : "确认发布"}</button>
      </div>
    </section>
  </WorkspaceDrawer>;
}
