import { useState } from "react";
import {
  analyzeDocumentTerms, getDocumentTermAnalysis, getEntity, getSourceCorpusState,
  type DocumentTermAnalysisState, type EntitySummary, type SourceCorpusState,
} from "../api";
import { Chip, EmptyState } from "../ui";
import { readList, readString, useResource, type SelectEntity } from "./PageShared";

type DocumentAnalysisMap = Record<string, DocumentTermAnalysisState | null>;
interface SourceLibraryState {
  relatedTerms: Array<{ id: string; title: string }>;
  corpus: SourceCorpusState | null;
}

export function LibraryDocumentsPanel({ documents, onOpen }: { documents: EntitySummary[]; onOpen: SelectEntity }) {
  const analysisResource = useResource<DocumentAnalysisMap>(
    `library-term-analysis:${documents.map((document) => document.id).join(",")}`,
    async () => Object.fromEntries(await Promise.all(documents.map(async (document) => {
      try {
        return [document.id, await getDocumentTermAnalysis(document.id)] as const;
      } catch {
        return [document.id, null] as const;
      }
    }))),
  );
  const [analysisTarget, setAnalysisTarget] = useState<EntitySummary | null>(null);
  const [transferConsent, setTransferConsent] = useState(false);
  const [analysisBusy, setAnalysisBusy] = useState(false);
  const [analysisError, setAnalysisError] = useState("");
  const [analysisNotice, setAnalysisNotice] = useState("");

  async function runAnalysis() {
    if (!analysisTarget || !transferConsent || analysisBusy) return;
    setAnalysisBusy(true);
    setAnalysisError("");
    setAnalysisNotice("");
    try {
      const result = await analyzeDocumentTerms(analysisTarget.id);
      setAnalysisNotice(`${analysisTarget.title}：新增 ${result.statistics.created_candidates}，复用 ${result.statistics.reused_candidates}，Existing ${result.statistics.existing}，New ${result.statistics.new}，跳过 ${result.statistics.skipped}。`);
      setAnalysisTarget(null);
      setTransferConsent(false);
      analysisResource.retry();
    } catch (reason) {
      setAnalysisError(reason instanceof Error ? reason.message : "Term Analysis 失败。");
    } finally {
      setAnalysisBusy(false);
    }
  }

  if (!documents.length) return <EmptyState title="Library 还是空的" description="发布一篇笔记后，它就会出现在这里。" />;

  return <div className="library-corpus-list">
    {analysisNotice && <p className="editor-notice success-notice" role="status">{analysisNotice}</p>}
    {documents.map((document) => {
      const analysis = analysisResource.data?.[document.id];
      const status = analysis?.status;
      const statusLabel = analysisResource.loading ? "Checking…"
        : status === "up_to_date" ? "Up to date"
          : status === "outdated" ? "Outdated"
            : status === "never_analyzed" ? "Never analyzed"
              : "Unavailable";
      const statusTone = status === "up_to_date" ? "green" : status === "outdated" ? "amber" : "neutral";
      const detail = [readString(document.metadata.type), document.id, ...readList(document.metadata, "domains"), ...readList(document.metadata, "topics")].filter(Boolean).join(" · ");
      return <article className="library-document-row surface" key={document.id}>
        <button type="button" className="library-record-main" onClick={() => onOpen("document", document.id)}>
          <span className="library-record-copy"><strong>{document.title}</strong><small>{detail}</small></span>
          <span className="library-record-state"><small>Canonical · Published</small><span>Term Analysis <Chip tone={statusTone}>{statusLabel}</Chip></span></span>
        </button>
        <div className="library-record-actions">
          <button type="button" className="button button-secondary" onClick={() => onOpen("document", document.id)}>Open Workspace</button>
          <button type="button" className="button button-primary" disabled={analysisBusy || analysisResource.loading} onClick={() => { setAnalysisError(""); setTransferConsent(false); setAnalysisTarget(document); }}>Analyze Terms</button>
        </div>
      </article>;
    })}
    {analysisTarget && <div className="explorer-modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !analysisBusy) setAnalysisTarget(null); }}>
      <section className="explorer-modal term-analysis-dialog surface" role="dialog" aria-modal="true" aria-labelledby="library-term-analysis-title">
        <div className="section-heading"><div><h2 id="library-term-analysis-title">分析 Canonical Note</h2><p>{analysisTarget.title} · Term Analysis 只使用已发布的正式内容。</p></div><button className="text-button" type="button" disabled={analysisBusy} onClick={() => setAnalysisTarget(null)}>关闭</button></div>
        <div className="term-analysis-transfer-copy"><p>本次会向 DeepSeek 发送这篇 Note 的正文和必要元数据、当前 Term Registry，以及该 Note 适用的拒绝记录，用于识别可复用概念、命名实体和阅读词汇。</p><p>不会发送其他 Notes 的全文，也不会自动把发现写入 Markdown；结果会进入 Candidates 等待审核。</p></div>
        <label className="ai-consent"><input type="checkbox" checked={transferConsent} disabled={analysisBusy} onChange={(event) => setTransferConsent(event.target.checked)} /><span>我同意将以上 Canonical Note 内容和所需 Registry 上下文发送给 DeepSeek。</span></label>
        {analysisError && <p className="error-copy" role="alert">{analysisError}</p>}
        <div className="term-candidate-dialog-actions"><button className="button button-secondary" type="button" disabled={analysisBusy} onClick={() => setAnalysisTarget(null)}>取消</button><button className="button button-primary" type="button" disabled={analysisBusy || !transferConsent} onClick={() => void runAnalysis()}>{analysisBusy ? "Analyzing…" : "同意并分析"}</button></div>
      </section>
    </div>}
  </div>;
}

export function LibrarySourcesPanel({ sources, onOpen }: { sources: EntitySummary[]; onOpen: SelectEntity }) {
  const resource = useResource<Record<string, SourceLibraryState>>(
    `library-source-state:${sources.map((source) => source.id).join(",")}`,
    async () => Object.fromEntries(await Promise.all(sources.map(async (source) => {
      const [detail, corpus] = await Promise.all([
        getEntity("source", source.id).catch(() => null),
        getSourceCorpusState(source.id).catch(() => null),
      ]);
      return [source.id, {
        relatedTerms: (detail?.related_terms ?? []).flatMap((term) => {
          const id = readString(term.id);
          return id ? [{ id, title: readString(term.title) || id }] : [];
        }),
        corpus,
      }] as const;
    }))),
  );

  if (!sources.length) return <EmptyState title="还没有来源文献" description="导入 PDF 或发布 Source 元数据后，可从这里打开来源。" />;

  return <div className="library-corpus-list">
    {sources.map((source) => {
      const state = resource.data?.[source.id];
      const pdfAttached = state?.corpus?.pdf_attached ?? Boolean(readString((source.metadata.attachments as Record<string, unknown> | undefined)?.local_pdf));
      const corpusStatus = state?.corpus?.extraction_status ?? "unavailable";
      const corpusLabel = resource.loading ? "Checking…" : corpusStatus === "ready" ? "Ready" : corpusStatus === "pending" ? "Pending" : corpusStatus === "failed" ? "Failed" : corpusStatus === "unavailable" ? "Unavailable" : corpusStatus === "not_extracted" ? "Not extracted" : corpusStatus === "no_pdf" ? "No PDF" : "Unknown";
      const usable = state?.corpus?.discovery_usable ?? false;
      const metadata = source.metadata;
      const relatedTerms = state?.relatedTerms ?? [];
      return <article className="library-source-row surface" key={source.id}>
        <div className="library-source-heading">
          <button type="button" className="library-record-main" onClick={() => onOpen("source", source.id)}>
            <span className="library-record-copy"><strong>{source.title}</strong><small>{[readString(metadata.type) || "Source", source.id, ...(Array.isArray(metadata.authors) ? metadata.authors.filter((author): author is string => typeof author === "string") : []), typeof metadata.year === "number" ? String(metadata.year) : ""].filter(Boolean).join(" · ")}</small></span>
            <span className="library-record-actions"><span className={`status-indicator ${pdfAttached ? "green" : "neutral"}`} /><span>{pdfAttached ? "PDF attached" : "No local PDF"}</span><span aria-hidden="true">↗</span></span>
          </button>
        </div>
        <div className="library-source-status">
          <div><small>Corpus extraction</small><Chip tone={corpusStatus === "ready" ? "green" : corpusStatus === "failed" || corpusStatus === "unavailable" ? "amber" : "neutral"}>{corpusLabel}</Chip></div>
          <div><small>Term Discovery</small><Chip tone={usable ? "green" : "neutral"}>{usable ? "Usable" : "Not usable"}</Chip></div>
        </div>
        <div className="library-source-terms"><small>Related Terms</small>{relatedTerms.length ? <div>{relatedTerms.map((term) => <button className="library-related-term" type="button" key={term.id} onClick={() => onOpen("term", term.id)}>{term.title}</button>)}</div> : <span>暂无关联 Terms</span>}</div>
        {state?.corpus?.error_message && <small className="library-source-error">{state.corpus.error_message}</small>}
      </article>;
    })}
  </div>;
}
