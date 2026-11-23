"""Module registry client for AzerothCore modules (GitHub topics-based)."""

import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

from .models import (
    ModuleCategory,
    ModuleManifest,
    ModuleSummary,
    ReleaseInfo,
)


class RegistryCache:
    """Disk cache for registry data."""

    def __init__(self, cache_dir: Path, ttl: int = 3600):
        self.cache_dir = cache_dir
        self.ttl = ttl
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.index_path = cache_dir / "index.json"
        self.manifests_dir = cache_dir / "manifests"
        self.manifests_dir.mkdir(exist_ok=True)

    def _is_fresh(self, path: Path) -> bool:
        if not path.exists():
            return False
        return (time.time() - path.stat().st_mtime) < self.ttl

    def get_index(self) -> dict[str, ModuleSummary] | None:
        if not self._is_fresh(self.index_path):
            return None
        try:
            with open(self.index_path) as f:
                data = json.load(f)
            return {k: ModuleSummary(**v) for k, v in data.items()}
        except Exception:
            return None

    def set_index(self, index: dict[str, ModuleSummary]) -> None:
        data = {k: v.model_dump(mode="json") for k, v in index.items()}
        with open(self.index_path, "w") as f:
            json.dump(data, f)

    def get_manifest(self, name: str) -> ModuleManifest | None:
        path = self.manifests_dir / f"{name}.json"
        if not self._is_fresh(path):
            return None
        try:
            with open(path) as f:
                data = json.load(f)
            return ModuleManifest(**data)
        except Exception:
            return None

    def set_manifest(self, manifest: ModuleManifest) -> None:
        path = self.manifests_dir / f"{manifest.name}.json"
        with open(path, "w") as f:
            json.dump(manifest.model_dump(mode="json"), f)


class GitHubRegistryClient:
    """Client for fetching module data from GitHub API."""

    BASE_URL = "https://api.github.com"
    SEARCH_URL = f"{BASE_URL}/search/repositories"
    REPO_URL = f"{BASE_URL}/repos"

    def __init__(
        self,
        token: str | None = None,
        cache_dir: Path | None = None,
        cache_ttl: int = 3600,
    ):
        self.token = token or os.environ.get("GITHUB_TOKEN")
        self.session = requests.Session()
        if self.token:
            self.session.headers["Authorization"] = f"token {self.token}"
        self.session.headers["Accept"] = "application/vnd.github.v3+json"
        default_cache = Path.home() / ".cache" / "yakeroth" / "registry"
        self.cache = RegistryCache(cache_dir or default_cache, cache_ttl)

    def _topic_to_category(self, topics: list[str]) -> list[ModuleCategory]:
        """Map GitHub topics to ModuleCategory."""
        mapping = {
            "azerothcore-module": ModuleCategory.MODULE,
            "azerothcore-tools": ModuleCategory.TOOL,
            "azerothcore-lua": ModuleCategory.LUA,
            "azerothcore-sql": ModuleCategory.SQL,
        }
        cats = []
        for topic in topics:
            if topic in mapping:
                cats.append(mapping[topic])
        return cats or [ModuleCategory.MODULE]

    def _extract_ac_compatibility(self, topics: list[str]) -> list[str]:
        """Extract AC version compatibility from topics like acore-rev-1-x."""
        return [t for t in topics if t.startswith("acore-rev-")]

    def _fetch_repo(self, full_name: str) -> dict[str, Any]:
        """Fetch repository metadata."""
        url = f"{self.REPO_URL}/{full_name}"
        resp = self.session.get(url)
        resp.raise_for_status()
        return resp.json()

    def _fetch_releases(self, full_name: str) -> list[ReleaseInfo]:
        """Fetch repository releases."""
        url = f"{self.REPO_URL}/{full_name}/releases"
        resp = self.session.get(url, params={"per_page": 50})
        resp.raise_for_status()
        releases = []
        for r in resp.json():
            if r.get("draft"):
                continue
            releases.append(ReleaseInfo(
                tag_name=r["tag_name"],
                name=r.get("name"),
                prerelease=r.get("prerelease", False),
                draft=r.get("draft", False),
                published_at=datetime.fromisoformat(r["published_at"].replace("Z", "+00:00")),
                assets=[a["name"] for a in r.get("assets", [])],
            ))
        return releases

    def _parse_dependencies(
        self, repo_data: dict[str, Any], readme: str | None = None
    ) -> list[dict[str, Any]]:
        """Extract dependencies from topics, description, README."""
        # For now, use topics that look like module names
        deps = []
        topics = repo_data.get("topics", [])
        for topic in topics:
            if topic.startswith("mod-") and topic not in [
                "azerothcore-module",
                "azerothcore-tools",
            ]:
                # This might be a dependency
                deps.append({"name": topic, "version": "*", "optional": False})
        return deps

    def build_manifest(
        self, repo_data: dict[str, Any], releases: list[ReleaseInfo]
    ) -> ModuleManifest:
        """Build ModuleManifest from GitHub repo data."""
        topics = repo_data.get("topics", [])
        categories = self._topic_to_category(topics)
        ac_compat = self._extract_ac_compatibility(topics)

        latest_release = releases[0].tag_name if releases else None

        return ModuleManifest(
            name=repo_data["name"],
            full_name=repo_data["full_name"],
            description=repo_data.get("description"),
            homepage=repo_data.get("homepage"),
            repository_url=repo_data["html_url"],
            categories=categories,
            topics=topics,
            latest_release=latest_release,
            releases=releases,
            default_branch=repo_data.get("default_branch", "master"),
            dependencies=self._parse_dependencies(repo_data),
            conflicts=[],
            provides=[],
            cmake_options={},
            sql_files=[],
            config_schema={},
            stars=repo_data.get("stargazers_count", 0),
            updated_at=(
                datetime.fromisoformat(repo_data["pushed_at"].replace("Z", "+00:00"))
                if repo_data.get("pushed_at")
                else None
            ),
            license=(
                repo_data.get("license", {}).get("spdx_id")
                if repo_data.get("license")
                else None
            ),
            ac_compatibility=ac_compat,
        )

    def search(
        self, query: str, category: ModuleCategory = ModuleCategory.MODULE, limit: int = 20
    ) -> list[ModuleSummary]:
        """Search modules via GitHub topics."""
        # Check cache first
        cached_index = self.cache.get_index()
        if cached_index:
            # Filter cached results
            results = []
            for summary in cached_index.values():
                if category and summary.categories and category not in summary.categories:
                    continue
                desc = summary.description or ""
                if query.lower() in summary.name.lower() or query.lower() in desc.lower():
                    results.append(summary)
                if len(results) >= limit:
                    break
            if results:
                return results

        # Build GitHub search query
        topic_map = {
            ModuleCategory.MODULE: "azerothcore-module",
            ModuleCategory.TOOL: "azerothcore-tools",
            ModuleCategory.LUA: "azerothcore-lua",
            ModuleCategory.SQL: "azerothcore-sql",
        }
        topic = topic_map.get(category, "azerothcore-module")
        q = f"topic:{topic} {query}" if query else f"topic:{topic}"

        url = self.SEARCH_URL
        params = {"q": q, "sort": "stars", "order": "desc", "per_page": limit}
        resp = self.session.get(url, params=params)
        resp.raise_for_status()

        items = resp.json().get("items", [])

        # Enrich with full repo data and cache
        index = {}
        for item in items:
            full_name = item["full_name"]
            repo_data = self._fetch_repo(full_name)
            releases = self._fetch_releases(full_name)
            manifest = self.build_manifest(repo_data, releases)
            self.cache.set_manifest(manifest)

            summary = ModuleSummary(
                name=manifest.name,
                full_name=manifest.full_name,
                description=manifest.description,
                stars=manifest.stars,
                updated_at=manifest.updated_at,
                latest_release=manifest.latest_release,
                categories=manifest.categories,
                topics=manifest.topics,
            )
            index[manifest.name] = summary

        self.cache.set_index(index)
        return list(index.values())[:limit]

    def get(self, name: str) -> ModuleManifest | None:
        """Get full manifest for a module by name."""
        # Check cache first
        cached = self.cache.get_manifest(name)
        if cached:
            return cached

        # Search to find the full_name
        results = self.search(name, limit=5)
        for summary in results:
            if summary.name.lower() == name.lower():
                return self.get(summary.full_name.split("/")[-1])

        return None

    def get_by_full_name(self, full_name: str) -> ModuleManifest | None:
        """Get manifest by owner/repo."""
        name = full_name.split("/")[-1]
        cached = self.cache.get_manifest(name)
        if cached:
            return cached

        repo_data = self._fetch_repo(full_name)
        releases = self._fetch_releases(full_name)
        manifest = self.build_manifest(repo_data, releases)
        self.cache.set_manifest(manifest)

        # Update index
        index = self.cache.get_index() or {}
        index[manifest.name] = ModuleSummary(
            name=manifest.name,
            full_name=manifest.full_name,
            description=manifest.description,
            stars=manifest.stars,
            updated_at=manifest.updated_at,
            latest_release=manifest.latest_release,
            categories=manifest.categories,
            topics=manifest.topics,
        )
        self.cache.set_index(index)

        return manifest


# Convenience function
def get_registry_client() -> GitHubRegistryClient:
    """Get configured registry client."""
    return GitHubRegistryClient()
