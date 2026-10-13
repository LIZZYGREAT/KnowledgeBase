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
  return <div className={`editor-notice publish-outcome-notice ${needsIndexRebuild ? "publish-warning-notice" : "success-notice"}`} role={needsIndexRebuild ? "alert" : "status"}>
    <strong>发布成功</strong>
    {hasWarnings && <details><summary>查看保存提醒（{outcome.warnings.length} 项）</summary><ul className="publish-outcome-warnings">{outcome.warnings.map((warning, index) => <li key={`${index}:${warning}`}>{warning}</li>)}</ul></details>}
    <details><summary>版本详情</summary><span>Git commit {outcome.commitRevision.slice(0, 12)}</span>{outcome.results.length > 0 && <span>已发布：{outcome.results.map((item) => `${item.entity_type} ${item.entity_id}`).join("、")}</span>}</details>
    {needsIndexRebuild && <p className="publish-outcome-recovery">内容已保存，但搜索索引更新失败。请运行 <code>python tools/kb.py rebuild</code> 恢复索引。</p>}
    {onReturn && <button className="button button-secondary" onClick={onReturn}>返回阅读</button>}
  </div>;
}
