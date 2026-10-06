"""Human-reviewed AI Proposal endpoints; prompts stay on the backend."""

from dataclasses import asdict
from typing import Optional

from fastapi import APIRouter, Request, status

from backend.app.api.schemas import (
    AIProposalView,
    AIRequest,
    SelectionReviewRequest,
    TermDraftRequest,
)


router = APIRouter(prefix="/api/ai", tags=["AI Proposals"])
_EXTERNAL_NOTICE = (
    "本次请求会向 DeepSeek 发送 Draft 内容及当前任务所需的注册表上下文。"
)


@router.post("/document-review", response_model=AIProposalView, status_code=status.HTTP_201_CREATED)
async def review_document(body: AIRequest, request: Request):
    return await _generate(request, "review_document", body.draft_id, {"document"})


@router.post("/metadata-suggest", response_model=AIProposalView, status_code=status.HTTP_201_CREATED)
async def suggest_metadata(body: AIRequest, request: Request):
    return await _generate(request, "suggest_metadata", body.draft_id, {"document"})


@router.post("/selection-review", response_model=AIProposalView, status_code=status.HTTP_201_CREATED)
async def review_selection(body: SelectionReviewRequest, request: Request):
    return await _generate(
        request,
        "review_format_semantics",
        body.draft_id,
        {"document"},
        {"selection": body.selection},
    )


@router.post("/term-draft", response_model=AIProposalView, status_code=status.HTTP_201_CREATED)
async def draft_term(body: TermDraftRequest, request: Request):
    extra_context = None
    if body.candidate_id:
        candidate = request.app.state.term_candidate_service.get_candidate(
            body.candidate_id
        )
        if candidate.status != "drafting" or candidate.draft_id != body.draft_id:
            raise ValueError("Term Candidate must be linked to this active Term Draft")
        evidence = [
            item
            for item in candidate.evidence
            if item.origin_type == "document" and not item.origin_rejected
        ][:5]
        if not evidence:
            raise ValueError("Term Candidate has no active Canonical Note evidence")
        extra_context = {
            "term_candidate": {
                "candidate_id": candidate.id,
                "display_name": candidate.display_name,
                "suggested_type": candidate.suggested_type,
                "note_evidence": [
                    {
                        "note_id": item.origin_id,
                        "note_title": item.origin_title or item.origin_id,
                        "context_excerpt": item.context_excerpt,
                        "rationale": item.rationale,
                    }
                    for item in evidence
                ],
            }
        }
    return await _generate(
        request, "draft_term", body.draft_id, {"term"}, extra_context
    )


@router.post("/evidence-suggest", response_model=AIProposalView, status_code=status.HTTP_201_CREATED)
async def suggest_evidence(body: AIRequest, request: Request):
    return await _generate(request, "suggest_evidence", body.draft_id, {"document"})


async def _generate(
    request: Request,
    task_name: str,
    draft_id: str,
    allowed_types: set[str],
    extra_context: Optional[dict] = None,
):
    draft = request.app.state.draft_service.get(draft_id)
    if draft.entity_type not in allowed_types:
        raise ValueError("{} requires a {} Draft".format(task_name, "/".join(sorted(allowed_types))))
    proposal = await request.app.state.ai_proposal_service.generate_async(
        task_name, draft_id, extra_context
    )
    return {"external_provider_notice": _EXTERNAL_NOTICE, "proposal": asdict(proposal)}
