"""Load and validate canonical Research Profiles and global settings."""

from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Mapping, Optional

import yaml
from pydantic import ValidationError

from backend.app.domain.research import ResearchGlobalConfig, ResearchProfile
from backend.app.services.collection_registry import CollectionRegistry
from backend.app.services.markdown_parser import parse_markdown, parse_yaml


@dataclass(frozen=True)
class ResearchProfileRegistry:
    global_config: ResearchGlobalConfig
    profiles: tuple[ResearchProfile, ...]
    _profile_paths: Mapping[str, Path]
    _profile_hashes: Mapping[str, str]

    @classmethod
    def load(cls, repository_root: Path) -> "ResearchProfileRegistry":
        root = Path(repository_root).resolve()
        config_path = root / "config" / "research" / "research.yaml"
        _reject_symlink(config_path, root)
        if not config_path.is_file():
            raise ValueError("config/research/research.yaml is required")
        global_config = _load_model(config_path, ResearchGlobalConfig)

        profiles_directory = root / "config" / "research" / "profiles"
        _reject_symlink(profiles_directory, root)
        profile_paths: dict[str, Path] = {}
        profile_hashes: dict[str, str] = {}
        profiles: list[ResearchProfile] = []
        errors: list[str] = []

        if profiles_directory.exists():
            for path in sorted(profiles_directory.iterdir()):
                _reject_symlink(path, root)
                if not path.is_file() or path.suffix != ".yaml":
                    errors.append(
                        "{}: expected a regular .yaml profile file".format(
                            path.relative_to(root).as_posix()
                        )
                    )
                    continue
                try:
                    profile = _load_model(path, ResearchProfile)
                except ValueError as error:
                    errors.append(str(error))
                    continue
                profiles.append(profile)
                profile_paths[profile.id] = path
                profile_hashes[profile.id] = hashlib.sha256(path.read_bytes()).hexdigest()

            ids = [profile.id for profile in profiles]
            duplicates = sorted({profile_id for profile_id in ids if ids.count(profile_id) > 1})
            for profile_id in duplicates:
                errors.append("Duplicate Research Profile id '{}'".format(profile_id))
            for profile in profiles:
                path = profile_paths[profile.id]
                if path.stem != profile.id:
                    errors.append(
                        "{}: filename must match Research Profile id '{}'".format(
                            path.relative_to(root).as_posix(), profile.id
                        )
                    )

        if errors:
            raise ValueError("Invalid Research configuration:\n- " + "\n- ".join(errors))

        profiles.sort(key=lambda profile: profile.id)
        _validate_references(root, profiles, profile_paths)
        return cls(global_config, tuple(profiles), profile_paths, profile_hashes)

    @classmethod
    def validate_candidate(
        cls, repository_root: Path, profile: ResearchProfile, profile_path: Path
    ) -> None:
        root = Path(repository_root).resolve()
        expected_path = (
            root / "config" / "research" / "profiles" / "{}.yaml".format(profile.id)
        )
        if Path(profile_path).resolve() != expected_path:
            raise ValueError(
                "Research Profile target path must match its id and canonical filename"
            )
        registry = cls.load(root)
        prospective_profiles = [
            existing for existing in registry.profiles if existing.id != profile.id
        ]
        prospective_profiles.append(profile)
        prospective_paths = dict(registry._profile_paths)
        prospective_paths[profile.id] = expected_path
        _validate_references(root, prospective_profiles, prospective_paths)

    def get(self, profile_id: str) -> Optional[ResearchProfile]:
        return next(
            (profile for profile in self.profiles if profile.id == profile_id), None
        )

    def content_hash(self, profile_id: str) -> str:
        if profile_id not in self._profile_hashes:
            raise LookupError("Research Profile '{}' does not exist".format(profile_id))
        return self._profile_hashes[profile_id]

    def path_for(self, profile_id: str) -> Path:
        if profile_id not in self._profile_paths:
            raise LookupError("Research Profile '{}' does not exist".format(profile_id))
        return self._profile_paths[profile_id]


def _load_model(path: Path, model_type):
    relative_name = path.as_posix()
    try:
        value = parse_yaml(path.read_text(encoding="utf-8"))
        return model_type.model_validate(value)
    except (OSError, UnicodeError, yaml.YAMLError, ValidationError) as error:
        raise ValueError("{}: {}".format(relative_name, error)) from error


def _validate_references(
    root: Path,
    profiles: list[ResearchProfile],
    profile_paths: Mapping[str, Path],
) -> None:
    try:
        collection_directory = root / "knowledge" / "collections"
        _reject_symlink(collection_directory, root)
        for path in collection_directory.iterdir() if collection_directory.exists() else ():
            _reject_symlink(path, root)
        collections = CollectionRegistry.load(collection_directory)
    except (OSError, UnicodeError, yaml.YAMLError, ValidationError, ValueError) as error:
        raise ValueError("Invalid canonical Collections: {}".format(error)) from error
    collection_ids = {collection.id for collection in collections.collections}
    document_directory = root / "knowledge" / "documents"
    _reject_symlink(document_directory, root)
    document_ids = _document_ids(document_directory)

    errors = []
    for profile in profiles:
        profile_path = profile_paths[profile.id].relative_to(root).as_posix()
        missing_collections = sorted(set(profile.context.collections) - collection_ids)
        missing_documents = sorted(set(profile.context.documents) - document_ids)
        if missing_collections:
            errors.append(
                "{}: unknown Collection id(s): {}".format(
                    profile_path, ", ".join(missing_collections)
                )
            )
        if missing_documents:
            errors.append(
                "{}: unknown pinned Document id(s): {}".format(
                    profile_path, ", ".join(missing_documents)
                )
            )
    if errors:
        raise ValueError("Invalid Research Profile references:\n- " + "\n- ".join(errors))


def _document_ids(directory: Path) -> set[str]:
    if not directory.exists():
        return set()
    identifiers = set()
    for path in sorted(directory.rglob("*.md")):
        if path.is_symlink():
            continue
        document = parse_markdown(path.read_text(encoding="utf-8"))
        if document.frontmatter:
            entity_id = document.frontmatter.get("id")
            if isinstance(entity_id, str):
                identifiers.add(entity_id)
    return identifiers


def _reject_symlink(path: Path, root: Path) -> None:
    try:
        relative_path = Path(path).relative_to(root)
    except ValueError as error:
        raise ValueError("Research configuration path is outside the repository: {}".format(path)) from error
    cursor = root
    for part in relative_path.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise ValueError(
                "Research configuration does not follow symlinks: {}".format(cursor)
            )
