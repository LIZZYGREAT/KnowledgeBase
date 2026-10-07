"""ASGI application and service composition."""

from contextlib import asynccontextmanager
import logging
from pathlib import Path
import os

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from backend.app.api.ai import router as ai_router
from backend.app.api.knowledge import router as knowledge_router
from backend.app.api.research import router as research_router
from backend.app.api.terms import router as terms_router
from backend.app.api.runtime import router as runtime_router
from backend.app.db.connection import connect_database
from backend.app.repositories.draft_repository import DraftRepository
from backend.app.repositories.draft_repository import DraftRevisionConflict
from backend.app.repositories.annotation_repository import AnnotationRepository
from backend.app.repositories.import_repository import ImportRepository
from backend.app.repositories.proposal_repository import ProposalRepository
from backend.app.repositories.term_candidate_repository import TermCandidateRepository
from backend.app.repositories.pdf_corpus_repository import PdfCorpusRepository
from backend.app.repositories.term_discovery_repository import TermDiscoveryRepository
from backend.app.services.ai_client import (
    AIConfigurationError,
    AIGatewayError,
    DeepSeekClient,
    DeepSeekConfig,
)
from backend.app.bootstrap import build_research_components
from backend.app.services.ai_gateway import AIGateway
from backend.app.services.ai_proposal_service import AIProposalService
from backend.app.services.canonical_target_resolver import CanonicalTargetResolver
from backend.app.services.draft_service import DraftService
from backend.app.services.git_manager import GitManager
from backend.app.services.import_service import ImportService
from backend.app.services.indexer import Indexer
from backend.app.services.proposal_service import ProposalService
from backend.app.services.publisher import (
    PublishConflictError,
    PublishError,
    PublishValidationError,
    Publisher,
)
from backend.app.services.import_service import ImportValidationError
from backend.app.services.proposal_service import StaleProposalError
from backend.app.repositories.proposal_repository import ProposalTransitionError
from backend.app.services.usage_service import UsageService
from backend.app.services.research_conversion_service import ResearchConversionService
from backend.app.services.term_candidate_service import (
    TermCandidateConflict,
    TermCandidateService,
)
from backend.app.services.term_merge_service import TermMergeConflict, TermMergeService
from backend.app.services.term_analysis_service import (
    TermAnalysisConflict,
    TermAnalysisService,
)
from backend.app.services.pdf_corpus_service import PdfCorpusService
from backend.app.services.term_discovery_service import TermDiscoveryService
from backend.app.services.presentation_annotation_service import (
    AnnotationConflictError,
    PresentationAnnotationService,
)
from backend.app.services.ui_summary_service import UiSummaryService
from backend.app.middleware import install_api_timing


@asynccontextmanager
async def lifespan(application: FastAPI):
    configured_root = os.environ.get("KNOWLEDGE_REPO_PATH")
    repository_root = Path(
        configured_root if configured_root else Path(__file__).resolve().parents[2]
    ).expanduser().resolve()
    configured_database = os.environ.get("DATABASE_PATH")
    database_path = (
        Path(configured_database).expanduser()
        if configured_database
        else repository_root / "runtime" / "knowledge.db"
    )
    if not database_path.is_absolute():
        database_path = repository_root / database_path

    connection = connect_database(database_path)
    try:
        git_manager = GitManager(repository_root)
        draft_service = DraftService(DraftRepository(connection))
        proposal_service = ProposalService(ProposalRepository(connection))
        term_candidate_repository = TermCandidateRepository(connection)
        canonical_target_resolver = CanonicalTargetResolver(repository_root, connection)
        term_candidate_service = TermCandidateService(
            repository_root,
            term_candidate_repository,
            draft_service,
            git_manager,
            canonical_target_resolver,
        )
        research_components = build_research_components(
            repository_root, connection, term_candidate_service
        )
        ai_gateway = AIGateway(
            DeepSeekClient(DeepSeekConfig.from_environment(repository_root))
        )
        ai_proposal_service = AIProposalService(
            repository_root, draft_service, proposal_service, ai_gateway
        )
        usage_service = UsageService(connection)
        annotation_service = PresentationAnnotationService(AnnotationRepository(connection))
        indexer = Indexer(repository_root, connection)
        pdf_corpus_service = PdfCorpusService(
            repository_root, PdfCorpusRepository(connection)
        )
        term_discovery_service = TermDiscoveryService(
            repository_root,
            TermDiscoveryRepository(connection),
            pdf_corpus_service,
            term_candidate_service,
            ai_gateway,
        )
        term_analysis_service = TermAnalysisService(
            repository_root,
            term_candidate_repository,
            term_candidate_service,
            ai_gateway,
            draft_service,
            canonical_target_resolver,
        )
        knowledge_read_service = research_components.knowledge_read_service
        collection_service = research_components.collection_service
        context_export_service = research_components.context_export_service
        import_service = ImportService(
            repository_root,
            ImportRepository(connection),
            draft_service,
            git_manager,
            canonical_target_resolver=canonical_target_resolver,
        )
        publisher = Publisher(
            repository_root,
            draft_service,
            indexer,
            proposal_service,
            git_manager,
            canonical_target_resolver=canonical_target_resolver,
        )
        term_merge_service = TermMergeService(
            repository_root,
            connection,
            term_candidate_repository,
            publisher,
            indexer,
        )
        research_service = research_components.research_service
        ui_summary_service = UiSummaryService(
            connection, research_service.profile_registry.profiles
        )
        research_conversion_service = ResearchConversionService(
            repository_root,
            connection,
            draft_service,
            git_manager,
            canonical_target_resolver,
        )
        publisher.add_post_publish_hook(
            research_conversion_service.finalize_published_drafts
        )
        publisher.add_post_publish_hook(
            term_candidate_service.finalize_published_drafts
        )
        publisher.add_post_publish_hook(research_service.refresh_canonical_state)

        application.state.repository_root = repository_root
        application.state.database_path = database_path
        application.state.runtime_connection = connection
        application.state.git_manager = git_manager
        application.state.draft_service = draft_service
        application.state.proposal_service = proposal_service
        application.state.term_candidate_service = term_candidate_service
        application.state.term_merge_service = term_merge_service
        application.state.term_analysis_service = term_analysis_service
        application.state.pdf_corpus_service = pdf_corpus_service
        application.state.term_discovery_service = term_discovery_service
        application.state.ai_gateway = ai_gateway
        application.state.ai_proposal_service = ai_proposal_service
        application.state.usage_service = usage_service
        application.state.annotation_service = annotation_service
        application.state.knowledge_read_service = knowledge_read_service
        application.state.collection_service = collection_service
        application.state.context_export_service = context_export_service
        application.state.indexer = indexer
        application.state.canonical_target_resolver = canonical_target_resolver
        application.state.import_service = import_service
        application.state.publisher = publisher
        application.state.research_service = research_service
        application.state.ui_summary_service = ui_summary_service
        application.state.research_conversion_service = research_conversion_service
        try:
            result = research_conversion_service.reconcile_pending_links()
            for warning in result["warnings"]:
                logging.getLogger(__name__).warning(
                    "Research conversion reconciliation: %s", warning
                )
        except Exception:
            logging.getLogger(__name__).exception(
                "Research conversion reconciliation failed during startup"
            )
        yield
    finally:
        connection.close()


app = FastAPI(title="KnowledgeBase API", version="0.8.0", lifespan=lifespan)
install_api_timing(app)
# Register fixed Term routes before the dynamic /api/terms/{entity_id} read route.
app.include_router(terms_router)
app.include_router(knowledge_router)
app.include_router(runtime_router)
app.include_router(ai_router)
app.include_router(research_router)


def _error_response(status_code: int, error: Exception) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"detail": str(error)})


@app.exception_handler(LookupError)
async def lookup_error_handler(request: Request, error: LookupError):
    return _error_response(404, error)


@app.exception_handler(DraftRevisionConflict)
async def draft_conflict_handler(request: Request, error: DraftRevisionConflict):
    return JSONResponse(
        status_code=409,
        content={
            "detail": str(error),
            "code": "draft_revision_conflict",
            "expected_revision": error.expected_revision,
            "current_revision": error.actual_revision,
        },
    )


@app.exception_handler(AnnotationConflictError)
async def annotation_conflict_handler(request: Request, error: AnnotationConflictError):
    return _error_response(409, error)


@app.exception_handler(ProposalTransitionError)
async def proposal_conflict_handler(request: Request, error: ProposalTransitionError):
    return _error_response(409, error)


@app.exception_handler(TermCandidateConflict)
async def term_candidate_conflict_handler(request: Request, error: TermCandidateConflict):
    return _error_response(409, error)


@app.exception_handler(TermAnalysisConflict)
async def term_analysis_conflict_handler(request: Request, error: TermAnalysisConflict):
    return _error_response(409, error)


@app.exception_handler(TermMergeConflict)
async def term_merge_conflict_handler(request: Request, error: TermMergeConflict):
    return _error_response(409, error)


@app.exception_handler(StaleProposalError)
async def stale_proposal_handler(request: Request, error: StaleProposalError):
    return _error_response(409, error)


@app.exception_handler(PublishConflictError)
async def publish_conflict_handler(request: Request, error: PublishConflictError):
    return _error_response(409, error)


@app.exception_handler(PublishValidationError)
async def publish_validation_handler(request: Request, error: PublishValidationError):
    return _error_response(422, error)


@app.exception_handler(PublishError)
async def publish_error_handler(request: Request, error: PublishError):
    return _error_response(409, error)


@app.exception_handler(ImportValidationError)
async def import_validation_handler(request: Request, error: ImportValidationError):
    return _error_response(422, error)


@app.exception_handler(AIConfigurationError)
async def ai_configuration_handler(request: Request, error: AIConfigurationError):
    return _error_response(503, error)


@app.exception_handler(AIGatewayError)
async def ai_gateway_error_handler(request: Request, error: AIGatewayError):
    return _error_response(502, error)


@app.exception_handler(ValidationError)
async def canonical_validation_handler(request: Request, error: ValidationError):
    return _error_response(422, error)


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, error: ValueError):
    return _error_response(422, error)
