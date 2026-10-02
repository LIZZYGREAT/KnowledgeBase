import type { PublishOutcome } from "../api";

export function PublishOutcomeNotice({
  outcome,
  onReturn,
}: {
  outcome: PublishOutcome;
  onReturn?: () => void;
}) {
  const hasWarnings = outcome.warnings.length > 0;
  const needsIndexRebuild = outcome.warnings.some((warning) => /index update failed/i.test(warning));
  return <div className={`editor-notice publish-outcome-notice ${hasWarnings ? "publish-warning-notice" : "success-notice"}`} role={hasWarnings ? "alert" : "status"}>
    <strong>{hasWarnings ? "发布成功，但需要处理以下警告" : "发布成功"}</strong>
    <span>Git commit {outcome.commitRevision.slice(0, 12)}</span>
    {outcome.results.length > 0 && <span>已发布：{outcome.results.map((item) => `${item.entity_type} ${item.entity_id}`).join("、")}</span>}
    {hasWarnings && <ul className="publish-outcome-warnings">{outcome.warnings.map((warning, index) => <li key={`${index}:${warning}`}>{warning}</li>)}</ul>}
    {needsIndexRebuild && <p className="publish-outcome-recovery">Canonical 已提交，但派生索引未完成更新。请运行 <code>python tools/kb.py rebuild</code> 恢复索引。</p>}
    {onReturn && <button className="button button-secondary" onClick={onReturn}>返回阅读</button>}
  </div>;
}
