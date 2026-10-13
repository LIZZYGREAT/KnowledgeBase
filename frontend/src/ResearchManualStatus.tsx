import { useEffect, useRef, useState } from "react";
import { listManualResearchRequests, type ManualResearchRequest } from "./api";
import { errorMessage } from "./errors";
import { formatDate } from "./ui";

export function ResearchManualStatus({ profileId, refreshKey, aiEnabled, onComplete, onResults, onRun }: {
  profileId: string; refreshKey: number; aiEnabled: boolean; onComplete: () => void;
  onResults?: () => void; onRun?: (id: string) => void;
}) {
  const [records, setRecords] = useState<ManualResearchRequest[]>([]);
  const [error, setError] = useState("");
  const [reload, setReload] = useState(0);
  const [paused, setPaused] = useState(false);
  const complete = useRef(onComplete);
  complete.current = onComplete;
  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    let attempts = 0;
    const activeIds = new Set<string>();
    setRecords([]);
    setPaused(false);
    async function load() {
      try {
        const result = await listManualResearchRequests(profileId);
        if (cancelled) return;
        setError("");
        setRecords(result);
        let finished = false;
        for (const item of result) {
          if (["pending", "claimed"].includes(item.request.status)) activeIds.add(item.request.id);
          else if (activeIds.delete(item.request.id)) finished = true;
        }
        if (finished) complete.current();
        if (result.some((item) => ["pending", "claimed"].includes(item.request.status))) {
          if (++attempts < 400) timer = setTimeout(() => void load(), 3000);
          else setPaused(true);
        }
      } catch (reason) {
        if (!cancelled) setError(errorMessage(reason));
      }
    }
    void load();
    return () => { cancelled = true; clearTimeout(timer); };
  }, [profileId, refreshKey, reload]);
  const item = records.find((record) => ["pending", "claimed"].includes(record.request.status)) ?? records[0];
  if (!item && !error) return null;
  const run = item?.run;
  const status = item?.request.status;
  const waiting = records.filter((record) => record.request.status === "pending").length;
  const label = status === "pending" ? "等待执行" : status === "claimed" ? (aiEnabled ? "正在检索与分析" : "正在检索") : status === "failed" ? "检索失败" : run?.status === "partial" ? "部分完成" : "检索已完成";
  return <div className="notice research-queued-notice" role="status">
    {error ? <p>暂时无法读取检索状态：{error}</p> : <>
      <strong>{label}</strong>
      <span>{formatDate(item!.request.claimed_at ?? item!.request.created_at)}{waiting > 0 ? ` · ${waiting} 项等待执行` : ""}</span>
      {run && status !== "claimed" && <p>检查 {run.fetched_count} 篇，新增 {run.new_work_count} 篇，分析 {run.analyzed_count} 篇，推荐 {run.surfaced_count} 篇。</p>}
      {status === "completed" && !run?.surfaced_count && <p>{!aiEnabled ? "AI 分析已关闭，本次只检索论文资料。" : "本次没有新增推荐，可调整检索主题或时间范围后再试。"}</p>}
      {status === "failed" && <p>请查看原因后，再通过“立即检索”重试。</p>}
      {run && <details><summary>运行详情</summary><p>{run.error_summary || "未记录异常。"}</p><p>任务：{item!.request.id} · 运行：{run.id}</p></details>}
      {status === "failed" && !run && <p>执行前检查失败，请检查研究方向是否启用、配置是否有效。</p>}
      {run && onRun && <button className="text-button" onClick={() => onRun(run.id)}>查看运行详情</button>}
      {status === "completed" && onResults && <button className="text-button" onClick={onResults}>查看新论文</button>}
    </>}
    {paused && <p>已暂停页面自动刷新，后台检索仍会继续。</p>}
    <button className="text-button" onClick={() => setReload((value) => value + 1)}>刷新状态</button>
  </div>;
}
