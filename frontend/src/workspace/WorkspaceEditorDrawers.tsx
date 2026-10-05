import { entityWorkspaceUrl } from "../workspaceRoute";
import type { WorkspaceEditorController } from "./useWorkspaceEditorController";
import { WorkspacePublishDrawer } from "./WorkspacePublishDrawer";
import { PublishOutcomeNotice } from "./PublishOutcomeNotice";
import { WorkspaceAIAssistDrawer } from "./WorkspaceAIAssistDrawer";
import { WorkspaceConflictDrawer } from "./WorkspaceConflictDrawer";
import { WorkspaceMetadataDrawer } from "./WorkspaceMetadataDrawer";
import { WorkspaceSourceDrawer } from "./WorkspaceSourceDrawer";

export function WorkspaceEditorDrawers({ controller }: { controller: WorkspaceEditorController }) {
  const {
    type, id, navigate, returnCollectionId,
    content, canonicalEntity, sourceEntries, sourceError, proposalError, proposalBusy, draftError,
    consent, setConsent, selection, setSelection, selectedText, saveError, setSaveError,
    proposals, publishing, activeDrawer, setActiveDrawer, publishReview, preflightBusy,
    publishedRevision, publishedOutcome, batchCollectionId, additionalDraftIds, comparison, mergeContent,
    setMergeContent, saveNow, runPreflight, reloadCanonical, applyRebase, generateProposal,
    actOnProposal, applyProposalToDraft, updateFrontmatter, updateFrontmatterList, updateSourcePdf,
    isDirty, saveState, setSelectedText,
  } = controller;

  return <>
    {publishedOutcome && <PublishOutcomeNotice
      outcome={publishedOutcome}
      onReturn={() => navigate(entityWorkspaceUrl(type, id, { collectionId: returnCollectionId }))}
    />}
    {activeDrawer === "metadata" && <WorkspaceMetadataDrawer
      type={type}
      id={id}
      content={content}
      canonicalSourceMetadata={canonicalEntity?.entity_type === "source" ? canonicalEntity.metadata : null}
      error={saveError || draftError}
      sourceEntries={sourceEntries}
      sourceError={sourceError}
      canonicalEvidenceCount={canonicalEntity?.evidence.length ?? 0}
      onFrontmatterUpdate={updateFrontmatter}
      onFrontmatterListUpdate={updateFrontmatterList}
      onSourcePdfChange={updateSourcePdf}
      onNavigate={navigate}
      onClose={() => setActiveDrawer(null)}
      onError={setSaveError}
    />}
    {activeDrawer === "source" && <WorkspaceSourceDrawer
      type={type}
      content={content}
      isDirty={isDirty}
      saveState={saveState}
      onChange={controller.setEditorContent}
      onSelectionChange={setSelectedText}
      onNavigate={navigate}
      onSave={() => void saveNow().catch(() => undefined)}
      onClose={() => setActiveDrawer(null)}
    />}
    {activeDrawer === "ai" && <WorkspaceAIAssistDrawer
      type={type}
      consent={consent}
      onConsentChange={setConsent}
      busy={proposalBusy}
      selection={selection}
      selectedText={selectedText}
      onSelectionChange={setSelection}
      proposalError={proposalError}
      proposals={proposals.filter((proposal) => ["proposed", "drafted"].includes(proposal.status))}
      pendingCount={proposals.filter((proposal) => ["proposed", "drafted"].includes(proposal.status)).length}
      onGenerate={(task) => void generateProposal(task)}
      onReview={(proposalId) => void actOnProposal(proposalId)}
      onApplyToDraft={(proposalId) => void applyProposalToDraft(proposalId)}
      onClose={() => setActiveDrawer(null)}
    />}
    {activeDrawer === "publish" && <WorkspacePublishDrawer
      items={publishReview ?? []}
      busy={preflightBusy}
      publishing={publishing}
      published={Boolean(publishedRevision)}
      error={saveError}
      batch={Boolean(batchCollectionId || additionalDraftIds.length)}
      onClose={() => setActiveDrawer(null)}
      onRefresh={() => void runPreflight()}
      onPublish={() => void controller.publishCurrentDraft()}
    />}
    {activeDrawer === "conflict" && comparison && <WorkspaceConflictDrawer
      comparison={comparison}
      content={content}
      mergeContent={mergeContent}
      onMergeContentChange={setMergeContent}
      onReloadCanonical={() => void reloadCanonical()}
      onApplyRebase={() => void applyRebase()}
      onClose={() => setActiveDrawer(null)}
    />}
  </>;
}
