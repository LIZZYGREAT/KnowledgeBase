"""Shared composition root for the Research Agent runtime."""

from pathlib import Path
import sqlite3

from backend.app.repositories.research_candidate_repository import (
    ResearchCandidateRepository,
)
from backend.app.repositories.research_repository import ResearchRepository
from backend.app.services.ai_client import DeepSeekClient, DeepSeekConfig
from backend.app.services.ai_gateway import AIGateway
from backend.app.services.collection_service import CollectionService
from backend.app.services.context_export_service import ContextExportService
from backend.app.services.knowledge_read_service import KnowledgeReadService
from backend.app.services.research_analysis_service import ResearchAnalysisService
from backend.app.services.research_candidate_service import ResearchCandidateService
from backend.app.services.research_context_builder import ResearchContextBuilder
from backend.app.services.research_profile_registry import ResearchProfileRegistry
from backend.app.services.research_providers import (
    ArxivProvider,
    CrossrefProvider,
    OpenAlexProvider,
)
from backend.app.services.research_service import ResearchService
from backend.app.services.source_registry import SourceRegistry


def assemble_research_service(
    repository_root: Path,
    connection: sqlite3.Connection,
    *,
    gateway: AIGateway,
    knowledge: KnowledgeReadService,
    collections: CollectionService,
    context_export: ContextExportService,
) -> ResearchService:
    """Assemble Research around services already owned by the API lifespan."""
    root = Path(repository_root).expanduser().resolve()
    registry = ResearchProfileRegistry.load(root)
    return _assemble_research_service(
        root,
        connection,
        registry=registry,
        gateway=gateway,
        knowledge=knowledge,
        collections=collections,
        context_export=context_export,
    )


def build_research_service_for_cli(
    repository_root: Path, connection: sqlite3.Connection
) -> ResearchService:
    """Build standalone dependencies for the Research CLI process."""
    root = Path(repository_root).expanduser().resolve()
    registry = ResearchProfileRegistry.load(root)
    configured_ai = DeepSeekConfig.from_environment(root)
    deepseek = DeepSeekConfig(
        api_key=configured_ai.api_key,
        model=configured_ai.model,
        base_url=configured_ai.base_url,
        timeout_seconds=registry.global_config.analysis.timeout_seconds,
        max_retries=configured_ai.max_retries,
    )
    gateway = AIGateway(DeepSeekClient(deepseek))
    knowledge = KnowledgeReadService(root, connection)
    collections = CollectionService(root, connection)
    context_export = ContextExportService(knowledge, connection)
    return _assemble_research_service(
        root,
        connection,
        registry=registry,
        gateway=gateway,
        knowledge=knowledge,
        collections=collections,
        context_export=context_export,
    )


def _assemble_research_service(
    root: Path,
    connection: sqlite3.Connection,
    *,
    registry: ResearchProfileRegistry,
    gateway: AIGateway,
    knowledge: KnowledgeReadService,
    collections: CollectionService,
    context_export: ContextExportService,
) -> ResearchService:
    provider_settings = registry.global_config.providers
    provider_options = {
        "timeout_seconds": provider_settings.timeout_seconds,
        "max_retries": provider_settings.max_retries,
    }
    providers = {
        "arxiv": ArxivProvider(**provider_options),
        "openalex": OpenAlexProvider(**provider_options),
        "crossref": CrossrefProvider(**provider_options),
    }

    work_repository = ResearchRepository(connection)
    candidate_service = ResearchCandidateService(
        ResearchCandidateRepository(connection)
    )
    context_builder = ResearchContextBuilder(
        knowledge,
        collections,
        context_export,
        registry.global_config.analysis.max_context_entities,
    )
    analysis_service = ResearchAnalysisService(work_repository, gateway)
    source_registry = SourceRegistry.load(root / "knowledge" / "sources")
    return ResearchService(
        repository_root=root,
        connection=connection,
        profile_registry=registry,
        providers=providers,
        context_builder=context_builder,
        analysis_service=analysis_service,
        candidate_service=candidate_service,
        source_registry=source_registry,
    )
