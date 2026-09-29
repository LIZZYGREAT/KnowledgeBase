"""ASGI application and Phase 0–6 service wiring."""

from contextlib import asynccontextmanager
from pathlib import Path
import os

from fastapi import FastAPI

from backend.app.db.connection import connect_database
from backend.app.repositories.draft_repository import DraftRepository
from backend.app.repositories.import_repository import ImportRepository
from backend.app.repositories.proposal_repository import ProposalRepository
from backend.app.services.ai_client import DeepSeekClient, DeepSeekConfig
from backend.app.services.ai_gateway import AIGateway
from backend.app.services.ai_proposal_service import AIProposalService
from backend.app.services.draft_service import DraftService
from backend.app.services.git_manager import GitManager
from backend.app.services.import_service import ImportService
from backend.app.services.indexer import Indexer
from backend.app.services.proposal_service import ProposalService
from backend.app.services.publisher import Publisher


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
        ai_gateway = AIGateway(
            DeepSeekClient(DeepSeekConfig.from_environment(repository_root))
        )
        ai_proposal_service = AIProposalService(
            repository_root, draft_service, proposal_service, ai_gateway
        )
        indexer = Indexer(repository_root, connection)
        import_service = ImportService(
            repository_root,
            ImportRepository(connection),
            draft_service,
            git_manager,
        )
        publisher = Publisher(
            repository_root,
            draft_service,
            indexer,
            proposal_service,
            git_manager,
        )

        application.state.repository_root = repository_root
        application.state.database_path = database_path
        application.state.runtime_connection = connection
        application.state.git_manager = git_manager
        application.state.draft_service = draft_service
        application.state.proposal_service = proposal_service
        application.state.ai_gateway = ai_gateway
        application.state.ai_proposal_service = ai_proposal_service
        application.state.indexer = indexer
        application.state.import_service = import_service
        application.state.publisher = publisher
        yield
    finally:
        connection.close()


app = FastAPI(title="KnowledgeBase API", version="0.1.0", lifespan=lifespan)
