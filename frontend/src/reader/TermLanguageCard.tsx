import { useState } from "react";
import { MarkdownContent as Markdown } from "../Markdown";
import { rejectProposal, requestTermRewrite, type Proposal } from "../api";
import { errorMessage } from "../errors";
import { splitMarkdownFrontmatter } from "../markdownBlocks";
import { replaceTermLanguage, termLanguageSections, type TermLanguage } from "../termLanguage";
import type { WorkspaceDraftController } from "../useWorkspaceDraft";
import type { Navigate } from "../pages/PageShared";

export function TermLanguageCard({ body, workspace, navigate, disabled }: { body: string; workspace: WorkspaceDraftController; navigate: Navigate; disabled: boolean }) {
  const [language, setLanguage] = useState<TermLanguage>("zh");
  const [editing, setEditing] = useState(false);
  const [newLanguage, setNewLanguage] = useState(false);
  const [rewriting, setRewriting] = useState(false);
  const [requirements, setRequirements] = useState("");
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const [comparisonOriginal, setComparisonOriginal] = useState("");
  const [comparisonLanguage, setComparisonLanguage] = useState<TermLanguage>("zh");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [actionFeedback, setActionFeedback] = useState("");
  const sections = termLanguageSections(body);
  const structured = Boolean(sections.zh || sections.en);
  const explanation = structured || newLanguage ? sections[language]?.content ?? "" : body;
  const rewriteBlockedReason = proposal
    ? "请先采用或放弃当前建议，再请求新的重写。"
    : !structured
      ? "原始正文尚未明确归入语言区块；请先整理为中文或 English 解释。"
      : !requirements.trim()
        ? "请输入重写要求。"
        : "";
  const proposedExplanation = proposal
    ? String((proposal.payload.result as Record<string, unknown> | undefined)?.explanation ?? "")
    : "";

  function changeExplanation(value: string) {
    const envelope = splitMarkdownFrontmatter(workspace.getCurrentContent());
    workspace.updateContent(envelope.frontmatter + (structured || newLanguage ? replaceTermLanguage(envelope.body, language, value) : value));
  }

  async function rewrite() {
    if (busy) return;
    if (rewriteBlockedReason) {
      setActionFeedback(rewriteBlockedReason);
      return;
    }
    setBusy(true);
    setError("");
    setActionFeedback("正在请求当前语言的重写建议…");
    try {
      const original = explanation;
      const draft = await workspace.saveNow() ?? await workspace.ensureDraft();
      const result = await requestTermRewrite(draft.id, language, requirements.trim());
      setComparisonOriginal(original);
      setComparisonLanguage(language);
      setProposal(result.proposal);
      setActionFeedback("重写建议已返回，仅供对比；当前 Draft 和正式知识尚未改变。");
    } catch (reason) {
      setError(errorMessage(reason));
      setActionFeedback("重写失败；输入仍保留，可检查错误后重试。");
    } finally {
      setBusy(false);
    }
  }

  async function adopt() {
    if (!proposal || busy) return;
    setBusy(true);
    setError("");
    setActionFeedback("正在将建议写入 Term Draft…");
    try {
      await workspace.applyProposalToDraft(proposal.id);
      setProposal(null);
      setRewriting(false);
      setActionFeedback("建议已采用到 Term Draft；仍需检查并单独发布。");
    } catch (reason) {
      setError(errorMessage(reason));
      setActionFeedback("采用失败；建议仍保留，可检查错误后重试。");
    } finally {
      setBusy(false);
    }
  }

  async function discardSuggestion() {
    if (!proposal || busy) return;
    setBusy(true);
    setError("");
    setActionFeedback("正在放弃这条建议…");
    try {
      await rejectProposal(proposal.id);
      setProposal(null);
      setActionFeedback("建议已放弃；Term Draft 未被修改。");
    } catch (reason) {
      setError(errorMessage(reason));
      setActionFeedback("放弃失败；建议仍保留，可检查错误后重试。");
    } finally {
      setBusy(false);
    }
  }

  return <section className="term-language-card surface" aria-label="Term 解释">
    <div className="term-language-actions">
      <div className="term-language-switch" role="group" aria-label="解释语言">
        <button type="button" className={`button ${language === "zh" ? "button-primary" : "button-secondary"}`} disabled={busy || Boolean(proposal)} aria-pressed={language === "zh"} onClick={() => { setLanguage("zh"); setActionFeedback(""); }}>中文</button>
        <button type="button" className={`button ${language === "en" ? "button-primary" : "button-secondary"}`} disabled={busy || Boolean(proposal)} aria-pressed={language === "en"} onClick={() => { setLanguage("en"); setActionFeedback(""); }}>English</button>
      </div>
      <button type="button" className="button button-secondary" disabled={disabled || busy} onClick={() => setEditing(!editing)}>{editing ? "完成编辑" : "编辑"}</button>
      <button type="button" className="button button-secondary" disabled={disabled || busy} onClick={() => setRewriting(!rewriting)}>{rewriting ? "关闭重写" : "AI 重写"}</button>
    </div>
    {!structured && <p className="subtle-copy">原有解释 · 保留原文，不推断语言 <button type="button" className="button button-secondary" disabled={busy || disabled} onClick={() => { setNewLanguage(true); setEditing(true); }}>新增独立的{language === "zh" ? "中文" : "English"}解释</button></p>}
    {editing && <label className="field-label">Markdown 源码<textarea value={explanation} onChange={(event) => changeExplanation(event.target.value)} disabled={disabled || busy} rows={8} /></label>}
    {explanation ? <Markdown content={explanation} onNavigate={navigate} /> : <p>暂无{language === "en" ? " English" : "中文"}解释。可编辑补充，或显式请求 AI 生成。</p>}
    {structured && <details><summary>完整原文与其他内容</summary><Markdown content={body} onNavigate={navigate} /></details>}
    {rewriting && <div className="term-language-rewrite">
      <label className="field-label">重写要求<textarea value={requirements} onChange={(event) => setRequirements(event.target.value)} disabled={disabled || busy} placeholder="例如：解释向量维度、来源和分类器如何使用，并给出简单例子" rows={2} /></label>
      <p className="subtle-copy">显式请求会将当前 Term Draft 发送给 DeepSeek；结果先供对比，不会自动采用或发布。</p>
      <button type="button" className="button button-primary" disabled={disabled || busy || Boolean(rewriteBlockedReason)} onClick={() => void rewrite()}>{busy && !proposal ? "正在生成…" : "生成当前语言建议"}</button>
      {rewriteBlockedReason && !busy && <p className="term-language-disabled-reason" role="status">{rewriteBlockedReason}</p>}
    </div>}
    {proposal && <details className="term-language-comparison" open>
      <summary>原文与建议对比 · {comparisonLanguage === "zh" ? "中文" : "English"}</summary>
      <div className="term-language-comparison-grid">
        <section aria-label="重写前解释"><h4>当前 Draft 原文</h4><div className="term-language-comparison-body"><Markdown content={comparisonOriginal} onNavigate={navigate} /></div></section>
        <section aria-label="尚未采用的重写建议"><h4>AI 建议 · 尚未采用</h4><div className="term-language-comparison-body"><Markdown content={proposedExplanation} onNavigate={navigate} /></div></section>
      </div>
      <div className="term-language-proposal-actions" role="group" aria-label="重写建议操作">
        <button type="button" className="button button-primary" disabled={disabled || busy} onClick={() => void adopt()}>{busy ? "正在采用…" : "采用到 Draft"}</button>
        <button type="button" className="button button-danger" disabled={busy} onClick={() => void discardSuggestion()}>{busy ? "处理中…" : "放弃建议"}</button>
      </div>
    </details>}
    {proposal && <p className="term-language-disabled-reason" role="status">请先处理当前重写建议，再切换解释语言或再次重写。</p>}
    {actionFeedback && <p className="term-language-action-feedback" role="status">{actionFeedback}</p>}
    {error && <p role="alert" className="error-copy">{error}</p>}
  </section>;
}
