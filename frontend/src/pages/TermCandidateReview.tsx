import { useEffect, useState } from "react";
import { parseDocument } from "yaml";
import { applyProposalToDraft, discardDraft, listProposals, preflightDraft, publishDraft, rejectProposal, rejectTermCandidate, requestCandidateTermDraftProposal, requestTermRewrite, type Draft, type Proposal, type TermCandidate } from "../api";
import { useRuntimeDraftSession } from "../draft/useRuntimeDraftSession";
import { MarkdownContent } from "../Markdown";
import { splitMarkdownFrontmatter } from "../markdownBlocks";
import { renumberTermH3Headings, termLanguageSections } from "../termLanguage";
import { errorMessage } from "../errors";

type ReviewAction = "close" | "depth" | "generate" | "rewrite" | "adopt" | "discard" | "repair" | "approve" | "reject";
type TermDepth = "stub" | "standard" | "deep";

const termDepthLabels: Record<TermDepth, string> = {
  stub: "基础速览",
  standard: "标准理解（默认）",
  deep: "系统深入",
};

const termDepthDescriptions: Record<TermDepth, string> = {
  stub: "完整说明含义、常见语境、用途和一个准确示例。",
  standard: "在完整基础上解释关键机制、流程、关系或输入输出。",
  deep: "在完整基础上按需补充原理、实现、假设、权衡、边界或反例。",
};

function readTermDepth(frontmatter: string): TermDepth {
  const yaml = frontmatter.replace(/^---\r?\n/, "").replace(/\r?\n---\r?\n?$/, "");
  const value = parseDocument(yaml).get("depth");
  return value === "stub" || value === "standard" || value === "deep" ? value : "standard";
}

function replaceTermDepth(frontmatter: string, depth: TermDepth): string {
  const depthLine = /^([ \t]*depth[ \t]*:[ \t]*)(["']?)(?:stub|standard|deep)\2([ \t]*(?:#.*)?)(\r?)$/m;
  if (!depthLine.test(frontmatter)) throw new Error("Term Draft frontmatter 中缺少有效的 depth。请在完整编辑器中检查。");
  return frontmatter.replace(depthLine, (_line, prefix: string, _quote: string, suffix: string, carriageReturn: string) => `${prefix}${depth}${suffix}${carriageReturn}`);
}

export function TermCandidateReview({ candidate, seed, onClose, onDone }: { candidate: TermCandidate; seed: Draft; onClose: () => void; onDone: (warnings?: string[]) => void }) {
  const session = useRuntimeDraftSession({ entityType: "term", entityId: seed.entity_id, enabled: true, initialContent: seed.content, initialContentReady: true });
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const [busyAction, setBusyAction] = useState<ReviewAction | null>(null);
  const [error, setError] = useState("");
  const [actionFeedback, setActionFeedback] = useState("");
  const [requirements, setRequirements] = useState("");
  const [editing, setEditing] = useState(false);
  const [proposalsLoading, setProposalsLoading] = useState(true);
  const [proposalLookupFailed, setProposalLookupFailed] = useState(false);
  const [preflightDetails, setPreflightDetails] = useState<string[]>([]);
  const envelope = splitMarkdownFrontmatter(session.content);
  const depth = readTermDepth(envelope.frontmatter);
  const proposedBody = proposal && typeof proposal.payload.content === "string" ? splitMarkdownFrontmatter(proposal.payload.content).body : "";
  const sections = termLanguageSections(envelope.body);
  const hasCurrentBody = Boolean(withoutLeadingTitle(envelope.body).trim());
  const hasLanguageExplanation = Boolean(sections.zh || sections.en);
  const headingRepair = renumberTermH3Headings(envelope.body);
  const rewriteBlockedReason = proposal
    ? "请先将当前建议采用到 Draft，或放弃建议，再重写。"
    : proposalsLoading
      ? "正在检查当前 Draft 是否有未处理建议。"
      : proposalLookupFailed
        ? "暂时无法确认当前建议状态，请重新打开审核后再操作。"
        : !hasLanguageExplanation
          ? "请先填写或生成至少一种语言的解释。"
        : "";
  const depthBlockedReason = proposal
    ? "请先采用或放弃当前建议，再更改深度。"
    : proposalsLoading
      ? "正在检查当前 Draft 是否有未处理建议。"
      : proposalLookupFailed
        ? "暂时无法确认当前建议状态，请重新打开审核后再调整深度。"
        : "";
  const locked = Boolean(busyAction) || session.loading || session.state === "runtime-conflict";

  useEffect(() => {
    let active = true;
    setProposalsLoading(true);
    setProposalLookupFailed(false);
    setProposal(null);
    void listProposals("proposed", "term", seed.entity_id).then((items) => {
      if (!active || !seed.working_content_hash) return;
      const matching = items.find((item) => isCandidateProposalReusable(item) && item.payload.draft_id === seed.id && item.base_content_hash === seed.working_content_hash) ?? null;
      if (matching) {
        setProposal(matching);
        setActionFeedback("已载入与当前 Draft 匹配的建议；建议仍未写入 Draft。可采用、放弃或稍后继续审核。");
      }
    }).catch((reason) => {
      if (active) {
        setProposalLookupFailed(true);
        setError(errorMessage(reason));
      }
    }).finally(() => { if (active) setProposalsLoading(false); });
    return () => { active = false; };
  }, [seed.id, seed.content, seed.entity_id, seed.working_content_hash]);

  async function changeDepth(nextDepth: TermDepth) {
    if (busyAction || depthBlockedReason) return;
    setBusyAction("depth");
    setError("");
    setActionFeedback("正在保存解释深度到当前 Term Draft…");
    try {
      const updatedContent = replaceTermDepth(envelope.frontmatter, nextDepth) + envelope.body;
      session.updateContent(updatedContent);
      const saved = await session.saveNow();
      if (!saved || saved.content !== updatedContent) throw new Error("无法确认所选深度已保存，请检查 Draft 状态后重试。");
      setActionFeedback(`深度已保存为「${termDepthLabels[nextDepth]}」；后续生成会读取当前 Draft。`);
    } catch (reason) {
      setError(errorMessage(reason));
      setActionFeedback("深度保存失败；选择仍保留在当前编辑中，生成请求尚未发送。");
    } finally {
      setBusyAction(null);
    }
  }

  async function generate(rewrite: boolean) {
    if (busyAction) return;
    if (rewrite && rewriteBlockedReason) {
      setActionFeedback(rewriteBlockedReason);
      return;
    }
    setBusyAction(rewrite ? "rewrite" : "generate");
    setError("");
    setActionFeedback(rewrite ? "正在请求中英文双语重写建议…" : "正在生成双语解释建议…");
    try {
      const draft = await session.saveNow();
      if (!draft || draft.content !== session.getCurrentContent()) throw new Error("无法确认当前 Term Draft 已保存，未发送 AI 请求。");
      if (rewrite) {
        const result = await requestTermRewrite(draft.id, requirements.trim());
        setProposal(result.proposal);
        setActionFeedback("中英文双语重写建议已生成，仅供对比；当前 Draft 和正式知识尚未改变。");
      } else {
        const existing = draft.working_content_hash
          ? (await listProposals("proposed", "term", draft.entity_id)).find((item) => isCandidateProposalReusable(item) && item.payload.draft_id === draft.id && item.base_content_hash === draft.working_content_hash)
          : undefined;
        if (existing) {
          setProposal(existing);
          setActionFeedback("已复用与当前 Draft 内容匹配的双语建议；没有重复请求 AI。");
        } else {
          setProposal((await requestCandidateTermDraftProposal(draft.id, candidate.id)).proposal);
          setActionFeedback("双语解释建议已生成，仅供对比；当前 Draft 和正式知识尚未改变。");
        }
      }
    } catch (reason) {
      setError(errorMessage(reason));
      setActionFeedback("操作失败。已保留当前编辑和建议内容，可检查错误后重试。");
    } finally {
      setBusyAction(null);
    }
  }

  async function adopt() {
    if (!proposal) return null;
    const draft = await session.saveNow() ?? seed;
    const result = await applyProposalToDraft(proposal.id, draft.id, draft.revision);
    session.acceptDraft(result.draft);
    setProposal(null);
    setActionFeedback("建议已采用到 Term Draft；仍需检查并单独发布。");
    return result.draft;
  }

  async function discardSuggestion() {
    if (!proposal || busyAction) return;
    setBusyAction("discard");
    setError("");
    setActionFeedback("正在放弃这条建议…");
    try {
      await rejectProposal(proposal.id);
      setProposal(null);
      setActionFeedback("建议已放弃；Term Draft 未被修改。");
    } catch (reason) {
      setError(errorMessage(reason));
      setActionFeedback("放弃失败；建议仍保留在当前页面。");
    } finally {
      setBusyAction(null);
    }
  }

  async function repairH3Numbering() {
    if (busyAction || proposal || headingRepair.correctedCount === 0) return;
    setBusyAction("repair");
    setError("");
    setPreflightDetails([]);
    setActionFeedback("正在只修正 H3 标题编号并保存 Draft…");
    try {
      const content = envelope.frontmatter + headingRepair.content;
      session.updateContent(content);
      const saved = await session.saveNow();
      if (!saved || saved.content !== content) throw new Error("无法确认编号修正已保存，请检查 Draft 状态后重试。");
      setActionFeedback(`已只修正 ${headingRepair.correctedCount} 个 H3 标题编号；解释正文保持不变，Draft 已保存，可检查后发布。`);
    } catch (reason) {
      setError(errorMessage(reason));
      setActionFeedback("H3 编号修正未保存；当前内容仍保留在编辑中，可检查错误后重试。");
    } finally {
      setBusyAction(null);
    }
  }

  async function closeReview() {
    if (busyAction) return;
    setBusyAction("close");
    setError("");
    setActionFeedback("正在保存当前 Draft…");
    try {
      const saved = await session.saveNow();
      if (!saved || saved.content !== session.getCurrentContent()) throw new Error("无法确认当前编辑已保存；请检查 Draft 状态后重试。");
      onClose();
    } catch (reason) {
      setError(errorMessage(reason));
      setActionFeedback("Draft 未关闭；当前编辑仍保留，可检查错误后重试。");
    } finally {
      setBusyAction(null);
    }
  }

  async function approve() {
    if (busyAction) return;
    setBusyAction("approve");
    setError("");
    setPreflightDetails([]);
    setActionFeedback("正在检查 Draft 并准备发布…");
    try {
      const adopted = proposal ? await adopt() : null;
      const current = adopted?.content ?? session.getCurrentContent();
      const parts = splitMarkdownFrontmatter(current);
      if (!parts.body.replace(/^#+.*$/gm, "").trim()) throw new Error("请先生成解释或人工填写，不能批准空白 Term。");
      const metadata = parseDocument(parts.frontmatter.replace(/^---\r?\n/, "").replace(/\r?\n---\r?\n?$/, ""));
      metadata.setIn(["review", "human", "status"], "approved");
      session.updateContent(`---\n${metadata.toString()}---\n${parts.body}`);
      const draft = await session.saveNow();
      if (!draft) throw new Error("Draft 保存失败，请重试。");
      setActionFeedback("Draft 已保存，正在运行 Preflight…");
      const preflight = await preflightDraft(draft.id);
      if (!preflight.valid || preflight.conflict) {
        const issues = [...preflight.errors, ...preflight.warnings];
        setPreflightDetails(issues);
        throw new Error(summarizePreflightIssues(issues) || "发布冲突，请打开完整编辑器处理。");
      }
      setActionFeedback("Preflight 通过，正在由 Publisher 发布…");
      const published = await publishDraft(draft.id, draft.revision);
      setActionFeedback("Term 已正式发布。");
      onDone(published.warnings);
    } catch (reason) {
      setError(errorMessage(reason));
      setActionFeedback("发布未完成；Draft 与输入仍保留，可修复后重试。");
    } finally {
      setBusyAction(null);
    }
  }

  async function reject() {
    if (busyAction) return;
    setBusyAction("reject");
    setError("");
    setActionFeedback("正在保存 Draft 并拒绝此建议…");
    try {
      const draft = await session.saveNow() ?? seed;
      await discardDraft(draft.id, draft.revision);
      await rejectTermCandidate(candidate.id, { scope: "global" });
      setActionFeedback("Term 建议已拒绝。");
      onDone();
    } catch (reason) {
      setError(errorMessage(reason));
      setActionFeedback("拒绝未完成；请检查错误后重试。");
    } finally {
      setBusyAction(null);
    }
  }

  return <section className="term-candidate-inline-review" aria-label="候选解释审核">
    <header className="term-candidate-review-heading">
      <div><h3>{candidate.display_name}</h3><p>当前任务：编辑 Term 解释。改动保存在 Draft，正式知识只会由 Publisher 发布。</p></div>
      <div className="term-candidate-review-heading-actions">
        <label className="field-label">解释深度<select aria-label="解释深度" value={depth} disabled={locked || Boolean(depthBlockedReason)} onChange={(event) => void changeDepth(event.target.value as TermDepth)}>
          <option value="stub">{termDepthLabels.stub}</option>
          <option value="standard">{termDepthLabels.standard}</option>
          <option value="deep">{termDepthLabels.deep}</option>
        </select></label>
        <button type="button" className="button button-quiet" disabled={locked} onClick={() => void closeReview()}>{busyAction === "close" ? "正在保存…" : "关闭编辑"}</button>
      </div>
    </header>
    <div className="term-candidate-edit-actions" role="group" aria-label="编辑或生成解释">
      <button type="button" className="button button-secondary" disabled={locked || Boolean(proposal) || proposalsLoading || proposalLookupFailed} onClick={() => setEditing(!editing)}>{editing ? "完成编辑" : "编辑 Markdown"}</button>
      {headingRepair.correctedCount > 0 && <button type="button" className="button button-secondary" disabled={locked || Boolean(proposal)} onClick={() => void repairH3Numbering()}>{busyAction === "repair" ? "正在修正…" : `修正 H3 编号（${headingRepair.correctedCount} 处）`}</button>}
      {hasCurrentBody && <button type="button" className="button button-secondary" disabled={locked || proposalsLoading || proposalLookupFailed} onClick={() => void generate(false)}>{busyAction === "generate" ? "正在生成…" : "重新生成双语解释"}</button>}
    </div>
    <p className="subtle-copy">{termDepthDescriptions[depth]}</p>
    {depthBlockedReason && <p className="term-candidate-disabled-reason" role="status">{depthBlockedReason}</p>}
    <p className="subtle-copy">显式生成会将当前 Term Draft、候选摘录和必要注册表发送给 DeepSeek；已有匹配建议会复用，AI 结果不会自动采用或发布。</p>
    {editing && <label className="field-label">Markdown 源码<textarea disabled={locked || Boolean(proposal)} value={envelope.body} rows={10} onChange={(event) => { const body = event.target.value; session.updateContent(envelope.frontmatter + (/^# /m.test(body) ? body : `# ${candidate.display_name}\n\n${body}`)); setActionFeedback("编辑内容只保存在 Draft；正式知识尚未改变。"); }} /></label>}
    {hasCurrentBody
      ? <div className="term-candidate-current-preview"><strong>当前 Term Draft</strong><MarkdownContent content={envelope.body} /></div>
      : <div className="term-candidate-empty-draft"><p>当前 Draft 尚无解释内容。</p>{!proposal && <button type="button" className="button button-primary" disabled={locked || proposalsLoading || proposalLookupFailed} onClick={() => void generate(false)}>{busyAction === "generate" ? "正在生成…" : "AI 生成双语解释"}</button>}</div>}
    {hasLanguageExplanation && <div className="term-candidate-rewrite-controls">
      <label className="field-label">AI 重写要求（可选）<textarea disabled={locked} rows={2} value={requirements} onChange={(event) => setRequirements(event.target.value)} placeholder="可留空；例如说明向量维度及分类器如何使用它" /></label>
      <button type="button" className="button button-secondary" disabled={locked || Boolean(rewriteBlockedReason)} onClick={() => void generate(true)}>{busyAction === "rewrite" ? "正在重写…" : "AI 双语重写"}</button>
      {rewriteBlockedReason && !busyAction && <p className="term-candidate-disabled-reason" role="status">{rewriteBlockedReason}</p>}
    </div>}
    {proposal && <details className="term-candidate-proposal-comparison" open>
      <summary>当前稿与双语建议对比</summary>
      {hasCurrentBody
        ? <div className="term-candidate-comparison-grid">
          <section aria-label="当前 Term Draft 原文"><h4>当前 Term Draft</h4><div className="term-candidate-comparison-body"><MarkdownContent content={withoutLeadingTitle(envelope.body)} /></div></section>
          <section aria-label="尚未采用的双语重写建议"><h4>双语 AI 建议 · 尚未采用</h4><div className="term-candidate-comparison-body"><MarkdownContent content={withoutLeadingTitle(proposedBody)} /></div></section>
        </div>
        : <section className="term-candidate-first-proposal" aria-label="尚未采用的双语重写建议"><p>初次生成：当前 Draft 没有原文。</p><div className="term-candidate-comparison-body"><MarkdownContent content={withoutLeadingTitle(proposedBody)} /></div></section>}
      <div className="term-candidate-suggestion-actions" role="group" aria-label="建议操作">
        <button type="button" className="button button-primary" disabled={locked} onClick={() => { setBusyAction("adopt"); setError(""); setActionFeedback("正在将建议写入 Draft…"); void adopt().catch((reason) => { setError(errorMessage(reason)); setActionFeedback("采用失败；建议仍保留，可检查错误后重试。"); }).finally(() => setBusyAction(null)); }}>{busyAction === "adopt" ? "正在采用…" : "采用到 Draft"}</button>
        <button type="button" className="button button-danger" disabled={locked} onClick={() => void discardSuggestion()}>{busyAction === "discard" ? "正在放弃…" : "放弃建议"}</button>
      </div>
    </details>}
    <div className="term-candidate-decision-actions" role="group" aria-label="审核决定">
      <button type="button" className="button button-primary" disabled={locked || !(proposedBody || envelope.body.replace(/^#+.*$/gm, "").trim())} onClick={() => void approve()}>{busyAction === "approve" ? "正在发布…" : "通过"}</button>
      <button type="button" className="button button-danger" disabled={locked} onClick={() => void reject()}>{busyAction === "reject" ? "正在拒绝…" : "拒绝"}</button>
    </div>
    {actionFeedback && <p className="term-candidate-action-feedback" role="status">{actionFeedback}</p>}
    {preflightDetails.length > 0 && <details className="term-candidate-preflight-details"><summary>查看 Preflight 详情</summary><ul>{preflightDetails.map((detail, index) => <li key={`${index}:${detail}`}>{detail}</li>)}</ul></details>}
    {(error || session.error) && <p role="alert" className="error-copy">{error || session.error}</p>}
  </section>;
}

function withoutLeadingTitle(body: string): string {
  return body.replace(/^# [^\r\n]*(?:\r?\n)+/, "");
}

function isCandidateProposalReusable(proposal: Proposal): boolean {
  return proposal.payload.task === "draft_term"
    || proposal.payload.task === "rewrite_term_bilingual";
}

function summarizePreflightIssues(issues: string[]): string {
  const items = issues.flatMap((issue) => issue.split("; "));
  const numberingCount = items.filter((issue) => issue.includes("heading.h3_numbering:")).length;
  const remaining = items.filter((issue) => !issue.includes("heading.h3_numbering:"));
  const summary = [];
  if (numberingCount) summary.push(`标题格式：${numberingCount} 个 H3 缺少“1. ”编号（可修正后重试）`);
  summary.push(...remaining);
  return summary.join("；");
}
