"""No-op gene installation adapter for runtimes without gene support.

Used as a fallback for runtimes that haven't implemented their own
GeneInstallAdapter. Deploys skills and scripts to generic paths without
runtime-specific config management.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.services.runtime.gene_install_adapter import GeneInstallAdapter

if TYPE_CHECKING:
    from app.services.nfs_mount import RemoteFS

logger = logging.getLogger(__name__)

SKILLS_DIR_REL = ".deskclaw/skills"
SCRIPTS_DIR_REL = ".deskclaw/tools"


class NoopGeneInstallAdapter(GeneInstallAdapter):
    def __init__(self, runtime_id: str = "unknown"):
        self.runtime_id = runtime_id

    async def deploy_skill(
        self, fs: RemoteFS, skill_name: str, content: str, description: str = "",
    ) -> None:
        await fs.mkdir(f"{SKILLS_DIR_REL}/{skill_name}")
        await fs.write_text(f"{SKILLS_DIR_REL}/{skill_name}/SKILL.md", content)

    async def deploy_scripts(self, fs: RemoteFS, scripts: dict[str, str]) -> None:
        if not scripts:
            return
        await fs.mkdir(SCRIPTS_DIR_REL)
        for filename, content in scripts.items():
            await fs.write_text(f"{SCRIPTS_DIR_REL}/{filename}", content)

    async def invalidate_cache(self, fs: RemoteFS, skill_name: str, event: str = "installed") -> None:
        logger.debug("NoopGeneInstallAdapter: cache invalidation not implemented for skill=%s", skill_name)

    async def remove_skill(self, fs: RemoteFS, skill_name: str) -> None:
        await fs.remove(f"{SKILLS_DIR_REL}/{skill_name}")

    async def post_remove_cleanup(self, fs: RemoteFS, skill_name: str) -> None:
        logger.debug(
            "NoopGeneInstallAdapter: post_remove_cleanup skipped for skill=%s "
            "(no runtime-specific cleanup logic)",
            skill_name,
        )
