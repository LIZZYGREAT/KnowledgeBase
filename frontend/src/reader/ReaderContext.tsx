import { useState, type ReactNode } from "react";
import { exportKnowledgeContext, type CollectionNavigation, type ContextPurpose, type ContextTrust, type EntityType, type ExportedContext } from "../api";
import { Chip } from "../ui";
import type { Navigate } from "../pages/PageShared";
export function CollectionReaderContext({
  navigation,
  loading,
  error,
  currentType,
  currentId,
  currentTitle,
  navigate,
}: {
  navigation: CollectionNavigation | null;
  loading: boolean;
  error: string;
  currentType: EntityType;
  currentId: string;
  currentTitle: string;
  navigate: Navigate;
}) {
  const openEntity = (type: EntityType, id: string) => {
    const prefix = type === "document" ? "documents" : type === "term" ? "terms" : "sources";
    const collectionId = navigation?.collection_id;
    const query = collectionId ? `?collection=${encodeURIComponent(collectionId)}` : "";
    navigate(`/${prefix}/${encodeURIComponent(id)}${query}`);
  };
  const leaveContext = () => {
    const prefix = currentType === "document" ? "documents" : currentType === "term" ? "terms" : "sources";
    navigate(`/${prefix}/${encodeURIComponent(currentId)}`);
  };

  return (
    <section className="collection-reader-context surface" aria-label="Collection 阅读位置">
      <div className="collection-reader-breadcrumbs">
        {navigation ? <>
          <span className="collection-reader-title">{navigation.collection_title}</span>
          {navigation.breadcrumbs.map((crumb, index) => <span className="collection-reader-crumb" key={`${crumb}:${index}`}>› {crumb}</span>)}
          <span className="collection-reader-current">› {currentTitle}</span>
        </> : loading ? <span>正在读取 Collection 位置…</span> : <span role="alert">{error || "Collection 位置暂不可用。"}</span>}
      </div>
      <div className="collection-reader-controls">
        {navigation?.previous ? <button className="button button-secondary" onClick={() => openEntity(navigation.previous!.entity_type, navigation.previous!.entity_id)}>← {navigation.previous.title}</button> : <span />}
        {navigation?.next ? <button className="button button-secondary" onClick={() => openEntity(navigation.next!.entity_type, navigation.next!.entity_id)}>{navigation.next.title} →</button> : <span />}
        {error && <button className="text-button" onClick={leaveContext}>打开独立阅读</button>}
      </div>
    </section>
  );
}

export function ContextCard({ id, className, title, detail, children }: { id?: string; className?: string; title: string; detail?: string; children: ReactNode }) {
  return <section id={id} className={`context-card surface ${className ?? ""}`}><div className="context-card-heading"><strong>{title}</strong>{detail && <small>{detail}</small>}</div>{children}</section>;
}

export function ContextExportPanel({ targetType, targetId }: { targetType: "document" | "source"; targetId: string }) {
  const [trust, setTrust] = useState<ContextTrust>("raw");
  const [purpose, setPurpose] = useState<ContextPurpose>("research");
  const [result, setResult] = useState<ExportedContext | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);

  async function createExport() {
    setBusy(true);
    setError("");
    setCopied(false);
    try {
      setResult(await exportKnowledgeContext(targetType, targetId, trust, purpose));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Context Export 失败。");
    } finally {
      setBusy(false);
    }
  }

  async function copyExport() {
    if (!result) return;
    try {
      await navigator.clipboard.writeText(JSON.stringify(result, null, 2));
      setCopied(true);
    } catch {
      setError("浏览器无法访问剪贴板；仍可手动复制下方 JSON。");
    }
  }

  return <ContextCard className="context-export-card" title="Context Export" detail="为研究任务导出有信任边界的知识包">
    <div className="context-export-controls">
      <label>Trust<select value={trust} onChange={(event) => setTrust(event.target.value as ContextTrust)}><option value="raw">Raw</option><option value="reviewed">Reviewed</option><option value="verified">Verified</option></select></label>
      <label>Purpose<select value={purpose} onChange={(event) => setPurpose(event.target.value as ContextPurpose)}><option value="research">Research</option><option value="teaching">Teaching</option><option value="evidence">Evidence</option></select></label>
      <button className="button button-secondary" disabled={busy} onClick={() => void createExport()}>{busy ? "正在导出…" : "生成 Context"}</button>
    </div>
    <p className="trust-note">Verified 是基于人工审批与 Source 元数据的临时追溯筛选，不代表每条 Evidence 都经过逐条核验。</p>
    {error && <p className="error-copy" role="alert">{error}</p>}
    {result && <div className="context-export-result"><div className="context-export-result-heading"><small>{result.trust} · {result.purpose}</small><button className="text-button" onClick={() => void copyExport()}>{copied ? "已复制" : "复制 JSON"}</button></div><pre>{JSON.stringify(result, null, 2)}</pre></div>}
  </ContextCard>;
}

export function MetaChipList({ values }: { values: string[] }) {
  if (!values.length) return <p className="subtle-copy">尚未添加分类。</p>;
  return <div className="meta-chip-list">{values.map((value) => <Chip key={value}>{value}</Chip>)}</div>;
}
