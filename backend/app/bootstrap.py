"""Shared Research composition root for the API and command-line tools."""

from dataclasses import dataclass
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


@dataclass(frozen=True)
class ResearchComponents:
    repository_root: Path
    profile_registry: ResearchProfileRegistry
    deepseek_config: DeepSeekConfig
    ai_gateway: AIGateway
    knowledge_read_service: KnowledgeReadService
    collection_service: CollectionService
    context_export_service: ContextExportService
    research_service: ResearchService


def load_research_configuration(
    repository_root: Path,
) -> tuple[ResearchProfileRegistry, DeepSeekConfig]:
    """Load canonical Research settings and normalize DeepSeek runtime settings."""
    root = Path(repository_root).expanduser().resolve()
    registry = ResearchProfileRegistry.load(root)
    configured_ai = DeepSeekConfig.from_environment(root)
    deepseek_config = DeepSeekConfig(
        api_key=configured_ai.api_key,
        model=configured_ai.model,
        base_url=configured_ai.base_url,
        timeout_seconds=registry.global_config.analysis.timeout_seconds,
        max_retries=configured_ai.max_retries,
    )
    return registry, deepseek_config


def build_research_components(
    repository_root: Path, connection: sqlite3.Connection
) -> ResearchComponents:
    """Create the same Research services for FastAPI and standalone commands."""
    root = Path(repository_root).expanduser().resolve()
    registry, deepseek_config = load_research_configuration(root)
    gateway = AIGateway(DeepSeekClient(deepseek_config))
    knowledge = KnowledgeReadService(root, connection)
    collections = CollectionService(root, connection)
    context_export = ContextExportService(knowledge, connection)

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
    analysis_service = ResearchAnalysisService(
        work_repository, gateway, repository_root=root
    )
    source_registry = SourceRegistry.load(root / "knowledge" / "sources")
    research_service = ResearchService(
        repository_root=root,
        connection=connection,
        profile_registry=registry,
        providers=providers,
        context_builder=context_builder,
        analysis_service=analysis_service,
        candidate_service=candidate_service,
        source_registry=source_registry,
    )
    return ResearchComponents(
        repository_root=root,
        profile_registry=registry,
        deepseek_config=deepseek_config,
        ai_gateway=gateway,
        knowledge_read_service=knowledge,
        collection_service=collections,
        context_export_service=context_export,
        research_service=research_service,
    )
