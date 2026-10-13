import { useEffect, useState } from "react";
import {
  analyzeDocumentTerms, getDocumentTermAnalysis, listTermCandidates,
  type DocumentTermAnalysisState, type LibraryDocumentState, type LibrarySourceState,
} from "../api";
import { Chip, EmptyState } from "../ui";
import { readList, readString, type Navigate, type SelectEntity } from "./PageShared";

type UncertainAnalysis = {
  documentId: string;
  documentTitle: string;
  baselineKnown: boolean;
  baselineAnalyzedAt: string | null;
};

type AnalysisVerification = {
  status: DocumentTermAnalysisState["status"];
  analyzedAt: string | null;
  linkedCandidateCount: number;
  completedAfterBaseline: boolean;
};

export function LibraryDocumentsPanel({ documents, onOpen, navigate, onAnalysisComplete }: { documents: LibraryDocumentState[]; onOpen: SelectEntity; navigate: Navigate; onAnalysisComplete: () => void }) {
  const [analysisTarget, setAnalysisTarget] = useState<LibraryDocumentState | null>(null);
  const [transferConsent, setTransferConsent] = useState(false);
  const [analysisBusy, setAnalysisBusy] = useState(false);
  const [analysisStage, setAnalysisStage] = useState<"baseline" | "request">("baseline");
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [analysisError, setAnalysisError] = useState("");
  const [analysisNotice, setAnalysisNotice] = useState<{ documentId: string; text: string; details?: string[] } | null>(null);
  const [uncertainAnalysis, setUncertainAnalysis] = useState<UncertainAnalysis | null>(null);
  const [analysisVerification, setAnalysisVerification] = useState<AnalysisVerification | null>(null);
  const [verificationBusy, setVerificationBusy] = useState(false);

  useEffect(() => {
    if (!analysisBusy) return;
    const startedAt = Date.now();
    setElapsedSeconds(0);
    const timer = window.setInterval(() => {
      setElapsedSeconds(Math.floor((Date.now() - startedAt) / 1000));
    }, 1000);
    return () => window.clearInterval(timer);
  }, [analysisBusy]);

  async function verifyUncertainAnalysis(target: UncertainAnalysis) {
    setVerificationBusy(true);
    setAnalysisVerification(null);
    try {
      const [state, candidates] = await Promise.all([
        getDocumentTermAnalysis(target.documentId),
        listTermCandidates(),
      ]);
      const linkedCandidateCount = candidates.filter((candidate) =>
        candidate.evidence.some((evidence) => evidence.origin_type === "document" && evidence.origin_id === target.documentId),
      ).length;
      setAnalysisVerification({
        status: state.status,
        analyzedAt: state.analyzed_at,
        linkedCandidateCount,
        completedAfterBaseline: Boolean(target.baselineKnown && state.analyzed_at && state.analyzed_at !== target.baselineAnalyzedAt),
      });
    } catch {
      setAnalysisError("只读核查暂时失败；尚不能确认结果。请稍后重新核查，或查看 待处理。分析请求不会自动重发。");
    } finally {
      setVerificationBusy(false);
    }
  }

  async function runAnalysis() {
    if (!analysisTarget || !transferConsent || analysisBusy) return;
    const target = analysisTarget;
    setAnalysisBusy(true);
    setAnalysisStage("baseline");
    setAnalysisError("");
    setAnalysisNotice(null);
    setUncertainAnalysis(null);
    setAnalysisVerification(null);
    let uncertainty: UncertainAnalysis | null = null;
    let baseline: DocumentTermAnalysisState | null = null;
    try {
      baseline = await getDocumentTermAnalysis(target.id).catch(() => null);
      setAnalysisStage("request");
      const result = await analyzeDocumentTerms(target.id);
      const discarded = result.statistics.invalid_candidates;
      setAnalysisNotice({
        documentId: target.id,
        text: `${target.title}：新增 ${result.statistics.created_candidates} 个待处理术语，复用 ${result.statistics.reused_candidates} 个已有候选。`,
        details: [`匹配已有术语 ${result.statistics.existing}，新术语 ${result.statistics.new}，跳过 ${result.statistics.skipped}，无效证据舍弃 ${discarded}。`, ...result.warnings],
      });
      setAnalysisTarget(null);
      setTransferConsent(false);
      onAnalysisComplete();
    } catch (reason) {
      if (isUncertainAnalysisError(reason)) {
        uncertainty = {
          documentId: target.id,
          documentTitle: target.title,
          baselineKnown: baseline !== null,
          baselineAnalyzedAt: baseline?.analyzed_at ?? null,
        };
        setUncertainAnalysis(uncertainty);
        setAnalysisError("请求连接中断，结果尚待确认。不会自动重发模型请求。");
      } else {
        setAnalysisError(reason instanceof Error ? reason.message : "术语分析 失败。");
      }
    } finally {
      setAnalysisBusy(false);
    }
    if (uncertainty) await verifyUncertainAnalysis(uncertainty);
  }

  function openCandidates(documentId: string) {
    navigate(`/terms?tab=candidates&document_id=${encodeURIComponent(documentId)}`);
  }

  if (!documents.length) return <EmptyState title="Library 还是空的" description="发布一篇笔记后，它就会出现在这里。" />;

  return <div className="library-corpus-list">
    {analysisNotice && <div className="editor-notice success-notice" role="status"><span>{analysisNotice.text}</span><button type="button" className="text-button" onClick={() => openCandidates(analysisNotice.documentId)}>查看待处理术语</button>{analysisNotice.details && <details><summary>分析详情</summary><ul>{analysisNotice.details.map((item, index) => <li key={index}>{item}</li>)}</ul></details>}</div>}
    {documents.map((document) => {
      const status = document.term_analysis_status;
      const statusLabel = status === "up_to_date" ? "已分析"
          : status === "outdated" ? "需要重新分析"
            : "尚未分析";
      const statusTone = status === "up_to_date" ? "green" : status === "outdated" ? "amber" : "neutral";
      const detail = [readString(document.metadata.type), document.id, ...readList(document.metadata, "domains"), ...readList(document.metadata, "topics")].filter(Boolean).join(" · ");
      return <article className="library-document-row surface" key={document.id}>
        <button type="button" className="library-record-main" onClick={() => onOpen("document", document.id)}>
          <span className="library-record-copy"><strong>{document.title}</strong><small>{detail}</small></span>
          <span className="library-record-state"><small>已收录</small><span>术语分析 <Chip tone={statusTone}>{statusLabel}</Chip></span></span>
        </button>
        <div className="library-record-actions">
          <button type="button" className="button button-secondary" onClick={() => onOpen("document", document.id)}>查看或编辑</button>
          <button type="button" className="button button-primary" disabled={analysisBusy} onClick={() => { setAnalysisError(""); setTransferConsent(false); setUncertainAnalysis(null); setAnalysisVerification(null); setAnalysisTarget(document); }}>分析术语</button>
        </div>
      </article>;
    })}
    {analysisTarget && <div className="explorer-modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !analysisBusy) setAnalysisTarget(null); }}>
      <section className="explorer-modal term-analysis-dialog surface" role="dialog" aria-modal="true" aria-labelledby="library-term-analysis-title">
        <div className="section-heading"><div><h2 id="library-term-analysis-title">分析 正式笔记</h2><p>{analysisTarget.title} · 术语分析 只使用已发布的正式内容。</p></div><button className="text-button" type="button" disabled={analysisBusy} onClick={() => setAnalysisTarget(null)}>关闭</button></div>
        <div className="term-analysis-transfer-copy"><p>本次会向 DeepSeek 发送这篇 笔记 的正文和必要元数据、当前 术语库，以及该 笔记 适用的拒绝记录，用于识别可复用概念、命名实体和阅读词汇。</p><p>不会发送其他 笔记 的全文，也不会自动把发现写入 Markdown；结果会进入 待处理 等待审核。</p></div>
        <label className="ai-consent"><input type="checkbox" checked={transferConsent} disabled={analysisBusy} onChange={(event) => setTransferConsent(event.target.checked)} /><span>我同意将以上 正式笔记 内容和所需 术语库 上下文发送给 DeepSeek。</span></label>
        {analysisError && <p className="error-copy" role="alert">{analysisError}</p>}
        {analysisBusy && <div className="term-analysis-running" role="status"><strong>{analysisStage === "baseline" ? "正在准备唯一一次分析请求…" : "正在请求 DeepSeek 分析这篇 笔记…"}</strong><span>已等待 {elapsedSeconds} 秒。分析可能需要一段时间，请勿重复提交。</span></div>}
        {uncertainAnalysis && <div className="term-analysis-verification surface" role="status">
          {verificationBusy ? <p>正在读取分析状态和这篇 笔记 关联的 待处理…</p> : analysisVerification ? <p>{analysisVerification.completedAfterBaseline && analysisVerification.status === "up_to_date"
            ? `分析状态已更新为 已分析（${formatAnalysisTime(analysisVerification.analyzedAt)}）；当前有 ${analysisVerification.linkedCandidateCount} 条 候选 关联这篇 笔记。`
            : `状态：${analysisStatusLabel(analysisVerification.status)}；当前有 ${analysisVerification.linkedCandidateCount} 条 候选 关联这篇 笔记，尚不能确认中断的请求已完成。`}</p> : <p>等待只读状态核查。</p>}
          <div className="term-candidate-dialog-actions"><button className="button button-secondary" type="button" disabled={verificationBusy} onClick={() => void verifyUncertainAnalysis(uncertainAnalysis)}>重新核查只读状态</button><button className="button button-quiet" type="button" onClick={() => openCandidates(uncertainAnalysis.documentId)}>查看 待处理</button></div>
        </div>}
        <div className="term-candidate-dialog-actions"><button className="button button-secondary" type="button" disabled={analysisBusy} onClick={() => setAnalysisTarget(null)}>取消</button><button className="button button-primary" type="button" disabled={analysisBusy || !transferConsent} onClick={() => void runAnalysis()}>{analysisBusy ? "Analyzing…" : "同意并分析"}</button></div>
      </section>
    </div>}
  </div>;
}

function isUncertainAnalysisError(reason: unknown): boolean {
  if (reason instanceof TypeError) return true;
  const status = typeof reason === "object" && reason !== null && "status" in reason
    ? (reason as { status?: unknown }).status
    : undefined;
  return typeof status === "number" && (status === 408 || status >= 500);
}

function analysisStatusLabel(status: DocumentTermAnalysisState["status"]): string {
  if (status === "up_to_date") return "已分析";
  if (status === "outdated") return "需要重新分析";
  return "尚未分析";
}

function formatAnalysisTime(value: string | null): string {
  if (!value) return "时间未知";
  const timestamp = new Date(value);
  return Number.isNaN(timestamp.getTime()) ? value : timestamp.toLocaleString();
}

export function LibrarySourcesPanel({ sources, onOpen }: { sources: LibrarySourceState[]; onOpen: SelectEntity }) {
  if (!sources.length) return <EmptyState title="还没有来源文献" description="导入 PDF 或发布 Source 元数据后，可从这里打开来源。" />;

  return <div className="library-corpus-list">
    {sources.map((source) => {
      const pdfAttached = source.pdf_attached;
      const corpusStatus = source.extraction_status;
      const corpusLabel = corpusStatus === "ready" ? "Ready" : corpusStatus === "pending" ? "Pending" : corpusStatus === "failed" ? "Failed" : corpusStatus === "unavailable" ? "Unavailable" : corpusStatus === "not_extracted" ? "Not extracted" : corpusStatus === "no_pdf" ? "No PDF" : "Unknown";
      const usable = source.discovery_usable;
      const metadata = source.metadata;
      const relatedTerms = source.related_terms;
      return <article className="library-source-row surface" key={source.id}>
        <div className="library-source-heading">
          <button type="button" className="library-record-main" onClick={() => onOpen("source", source.id)}>
            <span className="library-record-copy"><strong>{source.title}</strong><small>{[readString(metadata.type) || "Source", source.id, ...(Array.isArray(metadata.authors) ? metadata.authors.filter((author): author is string => typeof author === "string") : []), typeof metadata.year === "number" ? String(metadata.year) : ""].filter(Boolean).join(" · ")}</small></span>
            <span className="library-record-actions"><span className={`status-indicator ${pdfAttached ? "green" : "neutral"}`} /><span>{pdfAttached ? "PDF attached" : "No local PDF"}</span><span aria-hidden="true">↗</span></span>
          </button>
        </div>
        <div className="library-source-status">
          <div><small>Corpus extraction</small><Chip tone={corpusStatus === "ready" ? "green" : corpusStatus === "failed" || corpusStatus === "unavailable" ? "amber" : "neutral"}>{corpusLabel}</Chip></div>
          <div><small>发现术语</small><Chip tone={usable ? "green" : "neutral"}>{usable ? "Usable" : "Not usable"}</Chip></div>
        </div>
        <div className="library-source-terms"><small>Related 术语</small>{relatedTerms.length ? <div>{relatedTerms.map((term) => <button className="library-related-term" type="button" key={term.id} onClick={() => onOpen("term", term.id)}>{term.title}</button>)}</div> : <span>暂无关联 术语</span>}</div>
        {source.error_message && <small className="library-source-error">{source.error_message}</small>}
      </article>;
    })}
  </div>;
}
