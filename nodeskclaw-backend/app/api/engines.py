"""Portal-accessible engine listing endpoint."""

from fastapi import APIRouter, Depends

from app.core.security import get_current_user
from app.models.user import User
from app.schemas.common import ApiResponse
from app.services.runtime.registries.runtime_registry import RUNTIME_REGISTRY
from app.startup.seed import DEFAULT_REGISTRY_CONFIGS

router = APIRouter()


@router.get("", response_model=ApiResponse[list])
async def list_engines(_user: User = Depends(get_current_user)):
    engines = []
    for spec in RUNTIME_REGISTRY.all_runtimes():
        engines.append({
            "runtime_id": spec.runtime_id,
            "display_name": spec.display_name,
            "display_description": spec.display_description,
            "display_tags": list(spec.display_tags),
            "display_powered_by": spec.display_powered_by,
            "order": spec.order,
            "image_registry_key": spec.image_registry_key,
            "default_registry_url": DEFAULT_REGISTRY_CONFIGS.get(spec.image_registry_key, ""),
            "available": spec.available,
            "gateway_port": spec.gateway_port,
            "health_probe_path": spec.health_probe_path,
            "readiness_probe_path": spec.readiness_probe_path,
            "config_rel_path": spec.config_rel_path,
            "config_format": spec.config_format,
            "channels_section_key": spec.channels_section_key,
            "field_naming": spec.field_naming,
            "supports_channel_plugins": spec.supports_channel_plugins,
            "data_dir_container_path": spec.data_dir_container_path,
            "skills_dir_rel": spec.skills_dir_rel,
            "scripts_dir_rel": spec.scripts_dir_rel,
            "has_web_ui": spec.has_web_ui,
            "backup_dirs": list(spec.backup_dirs),
            "backup_exclude_patterns": list(spec.backup_exclude_patterns),
            "capabilities": spec.capability_map(),
        })
    engines.sort(key=lambda r: r["order"])
    return ApiResponse(data=engines)
