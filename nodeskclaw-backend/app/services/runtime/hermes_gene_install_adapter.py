"""Hermes-specific gene installation adapter."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.services.runtime.gene_install_adapter import GeneInstallAdapter

if TYPE_CHECKING:
    from app.services.nfs_mount import RemoteFS


class HermesGeneInstallAdapter(GeneInstallAdapter):
    runtime_id = "hermes"

    def __init__(
        self,
        skills_dir_rel: str = ".hermes/skills",
        scripts_dir_rel: str = ".hermes/scripts",
        snapshot_rel: str = ".hermes/.skills_prompt_snapshot.json",
        legacy_skills_dir_rel: str = ".deskclaw/skills",
    ):
        self._skills_dir = skills_dir_rel
        self._scripts_dir = scripts_dir_rel
        self._snapshot_rel = snapshot_rel
        self._legacy_skills_dir = legacy_skills_dir_rel

    async def deploy_skill(
        self,
        fs: RemoteFS,
        skill_name: str,
        content: str,
        description: str = "",
    ) -> None:
        await fs.remove(f"{self._legacy_skills_dir}/{skill_name}")
        content = _normalize_skill_content(content)
        if not content.lstrip().startswith("---"):
            desc = description or f"Skill: {skill_name}"
            content = f"---\nname: {skill_name}\ndescription: {desc}\n---\n\n{content}"

        await fs.mkdir(f"{self._skills_dir}/{skill_name}")
        await fs.write_text(f"{self._skills_dir}/{skill_name}/SKILL.md", content)

    async def deploy_scripts(self, fs: RemoteFS, scripts: dict[str, str]) -> None:
        if not scripts:
            return
        await fs.mkdir(self._scripts_dir)
        for filename, content in scripts.items():
            await fs.write_text(f"{self._scripts_dir}/{filename}", content)

    async def invalidate_cache(self, fs: RemoteFS, skill_name: str, event: str = "installed") -> None:
        await fs.remove(self._snapshot_rel)

    async def remove_skill(self, fs: RemoteFS, skill_name: str) -> None:
        await fs.remove(f"{self._skills_dir}/{skill_name}")
        await fs.remove(f"{self._legacy_skills_dir}/{skill_name}")

    async def post_remove_cleanup(self, fs: RemoteFS, skill_name: str) -> None:
        await fs.remove(self._snapshot_rel)


def _normalize_skill_content(content: str) -> str:
    replacements = (
        ("~/.deskclaw/tools", "~/.hermes/scripts"),
        ("/root/.deskclaw/tools", "~/.hermes/scripts"),
        (".deskclaw/tools", ".hermes/scripts"),
    )
    normalized = content
    for old, new in replacements:
        normalized = normalized.replace(old, new)
    return normalized
