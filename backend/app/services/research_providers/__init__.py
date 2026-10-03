"""Offline-testable adapters for scholarly metadata providers."""

from .arxiv import ArxivProvider
from .base import (
    ProviderPage,
    ProviderResponseError,
    ProviderWork,
    ResearchHttpClient,
    ResearchProvider,
    ResearchProviderError,
)
from .crossref import CrossrefProvider
from .openalex import OpenAlexProvider

__all__ = [
    "ArxivProvider",
    "CrossrefProvider",
    "OpenAlexProvider",
    "ProviderPage",
    "ProviderResponseError",
    "ProviderWork",
    "ResearchHttpClient",
    "ResearchProvider",
    "ResearchProviderError",
]
