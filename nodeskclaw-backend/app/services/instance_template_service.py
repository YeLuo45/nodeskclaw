"""Instance template CRUD service."""

import json
import logging
import re
from pathlib import Path
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import BadRequestError, ConflictError, NotFoundError
from app.models.base import not_deleted
from app.models.gene import ContentVisibility, Gene, GeneSource, Genome, InstanceGene
from app.models.instance import Instance
from app.models.instance_template import InstanceTemplate, InstanceTemplateType, TemplateItem
from app.schemas.instance_template import (
    AgentBundleImportRequest,
    GeneRef,
    InstanceTemplateCreate,
    InstanceTemplateFromInstance,
    InstanceTemplateInfo,
    InstanceTemplateUpdate,
    TemplateItemInput,
    TemplateItemRef,
)
from app.services.agent_bundle_service import (
    SECRET_REF_SOURCE_NAMESPACE_KEY,
    build_bundle_env_vars,
    normalize_bundle_slug,
    parse_agent_bundle_dir,
    sanitize_agent_bundle_manifest,
    summarize_agent_bundle_manifest,
)

logger = logging.getLogger(__name__)


def _can_read_template(tpl: InstanceTemplate, org_id: str | None) -> bool:
    return tpl.visibility == "public" or tpl.org_id == org_id


def _can_manage_template(tpl: InstanceTemplate, org_id: str | None) -> bool:
    return tpl.org_id == org_id


async def _get_template_model(
    db: AsyncSession,
    template_id: str,
    org_id: str | None,
    *,
    require_manage: bool = False,
) -> InstanceTemplate:
    result = await db.execute(
        select(InstanceTemplate).where(InstanceTemplate.id == template_id, not_deleted(InstanceTemplate))
    )
    tpl = result.scalar_one_or_none()
    if not tpl:
        raise NotFoundError("AI 员工模板不存在")
    if require_manage:
        if not _can_manage_template(tpl, org_id):
            raise NotFoundError("AI 员工模板不存在")
    elif not _can_read_template(tpl, org_id):
        raise NotFoundError("AI 员工模板不存在")
    return tpl


def _parse_gene_slugs(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []


def _parse_json_obj(raw: str | None) -> dict[str, Any] | None:
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def _clean_template_display_name(value: str | None) -> str | None:
    cleaned = str(value or "").strip()
    return cleaned[:128] if cleaned else None


def _suggest_agent_bundle_display_name(manifest: dict[str, Any]) -> str | None:
    config = manifest.get("config") if isinstance(manifest.get("config"), dict) else {}
    explicit_candidates = [
        manifest.get("display_name"),
        manifest.get("displayName"),
        config.get("display_name"),
        config.get("displayName"),
        config.get("zhName"),
        config.get("chineseName"),
    ]
    for candidate in explicit_candidates:
        cleaned = _clean_template_display_name(candidate)
        if cleaned:
            return cleaned
    return None


_EXPERT_PLACEHOLDER_RE = re.compile(r"^专家([1-9]\d*)$")


def _next_agent_bundle_placeholder_name(existing_names: list[str]) -> str:
    used: set[int] = set()
    for name in existing_names:
        match = _EXPERT_PLACEHOLDER_RE.match(str(name or "").strip())
        if match:
            used.add(int(match.group(1)))
    index = 1
    while index in used:
        index += 1
    return f"专家{index}"


async def _suggest_next_agent_bundle_display_name(db: AsyncSession, org_id: str | None) -> str:
    result = await db.execute(
        select(InstanceTemplate.name).where(
            InstanceTemplate.template_type == InstanceTemplateType.agent_bundle,
            InstanceTemplate.org_id == org_id,
            not_deleted(InstanceTemplate),
        )
    )
    return _next_agent_bundle_placeholder_name([name for name in result.scalars().all() if name])


async def _resolve_gene_refs(db: AsyncSession, slugs: list[str]) -> list[GeneRef]:
    if not slugs:
        return []
    result = await db.execute(
        select(Gene).where(Gene.slug.in_(slugs), not_deleted(Gene))
    )
    gene_map = {g.slug: g for g in result.scalars().all()}
    return [
        GeneRef(
            slug=s,
            name=gene_map[s].name if s in gene_map else s,
            short_description=gene_map[s].short_description if s in gene_map else None,
            category=gene_map[s].category if s in gene_map else None,
            icon=gene_map[s].icon if s in gene_map else None,
        )
        for s in slugs
    ]


async def _resolve_item_refs(
    db: AsyncSession, items: list[TemplateItem],
) -> list[TemplateItemRef]:
    if not items:
        return []

    gene_slugs = [i.item_slug for i in items if i.item_type == "gene"]
    genome_slugs = [i.item_slug for i in items if i.item_type == "genome"]

    gene_map: dict[str, Gene] = {}
    if gene_slugs:
        res = await db.execute(
            select(Gene).where(Gene.slug.in_(gene_slugs), not_deleted(Gene))
        )
        gene_map = {g.slug: g for g in res.scalars().all()}

    genome_map: dict[str, Genome] = {}
    if genome_slugs:
        res = await db.execute(
            select(Genome).where(Genome.slug.in_(genome_slugs), not_deleted(Genome))
        )
        genome_map = {g.slug: g for g in res.scalars().all()}

    refs: list[TemplateItemRef] = []
    for item in items:
        if item.item_type == "gene":
            g = gene_map.get(item.item_slug)
            refs.append(TemplateItemRef(
                type="gene",
                slug=item.item_slug,
                name=g.name if g else item.item_slug,
                short_description=g.short_description if g else None,
                icon=g.icon if g else None,
            ))
        else:
            gm = genome_map.get(item.item_slug)
            gene_count = None
            if gm:
                try:
                    gene_count = len(json.loads(gm.gene_slugs or "[]"))
                except (json.JSONDecodeError, TypeError):
                    gene_count = 0
            refs.append(TemplateItemRef(
                type="genome",
                slug=item.item_slug,
                name=gm.name if gm else item.item_slug,
                short_description=gm.short_description if gm else None,
                icon=gm.icon if gm else None,
                gene_count=gene_count,
            ))
    return refs


async def _get_template_items(db: AsyncSession, template_id: str) -> list[TemplateItem]:
    result = await db.execute(
        select(TemplateItem)
        .where(TemplateItem.template_id == template_id, not_deleted(TemplateItem))
        .order_by(TemplateItem.sort_order)
    )
    return list(result.scalars().all())


async def _write_template_items(
    db: AsyncSession, template_id: str, inputs: list[TemplateItemInput],
) -> None:
    for idx, inp in enumerate(inputs):
        db.add(TemplateItem(
            template_id=template_id,
            item_type=inp.type,
            item_slug=inp.slug,
            sort_order=idx,
        ))


async def _soft_delete_template_items(db: AsyncSession, template_id: str) -> None:
    existing = await _get_template_items(db, template_id)
    for item in existing:
        item.soft_delete()


def _is_agent_bundle_template(tpl: InstanceTemplate) -> bool:
    return tpl.template_type in (InstanceTemplateType.agent_bundle, InstanceTemplateType.agent_bundle.value)


def _is_trusted_platform_agent_bundle_template(tpl: InstanceTemplate) -> bool:
    return (
        _is_agent_bundle_template(tpl)
        and getattr(tpl, "org_id", None) is None
        and getattr(tpl, "visibility", None) in (ContentVisibility.public, ContentVisibility.public.value)
    )


def _template_agent_bundle_manifest(
    tpl: InstanceTemplate,
    *,
    include_platform_secret_source: bool = False,
    allow_invalid_secret_refs: bool = False,
) -> dict[str, Any] | None:
    manifest = _parse_json_obj(tpl.agent_bundle_manifest)
    if not _is_agent_bundle_template(tpl):
        return manifest
    try:
        sanitized = sanitize_agent_bundle_manifest(manifest)
    except BadRequestError as exc:
        if not allow_invalid_secret_refs:
            raise
        logger.warning(
            "忽略历史 Agent Bundle 模板中的非法 secretRefs: template_id=%s slug=%s err=%s",
            getattr(tpl, "id", None),
            getattr(tpl, "slug", None),
            exc.message,
        )
        sanitized = dict(manifest or {})
        sanitized.pop("secretRefs", None)
        sanitized.pop("secret_refs", None)
        sanitized.pop(SECRET_REF_SOURCE_NAMESPACE_KEY, None)
    if (
        sanitized
        and include_platform_secret_source
        and _is_trusted_platform_agent_bundle_template(tpl)
        and sanitized.get("secret_refs")
    ):
        sanitized[SECRET_REF_SOURCE_NAMESPACE_KEY] = settings.PLATFORM_NAMESPACE
    return sanitized


def _template_to_info(
    tpl: InstanceTemplate,
    genes: list[GeneRef] | None = None,
    item_refs: list[TemplateItemRef] | None = None,
) -> InstanceTemplateInfo:
    items = item_refs or []
    gene_slugs_from_items = [r.slug for r in items if r.type == "gene"]
    legacy_slugs = gene_slugs_from_items if items else _parse_gene_slugs(tpl.gene_slugs)
    agent_bundle_manifest = _template_agent_bundle_manifest(tpl, allow_invalid_secret_refs=True)

    return InstanceTemplateInfo(
        id=tpl.id,
        name=tpl.name,
        slug=tpl.slug,
        description=tpl.description,
        short_description=tpl.short_description,
        icon=tpl.icon,
        gene_slugs=legacy_slugs,
        genes=genes or [],
        items=items,
        template_type=tpl.template_type or InstanceTemplateType.basic,
        agent_bundle=summarize_agent_bundle_manifest(agent_bundle_manifest),
        resource_recommendation=_parse_json_obj(tpl.resource_recommendation),
        upload_contract=_parse_json_obj(tpl.upload_contract),
        secret_refs=(agent_bundle_manifest or {}).get("secret_refs") or [],
        bundle_storage_key=tpl.bundle_storage_key,
        source_instance_id=tpl.source_instance_id,
        is_published=tpl.is_published,
        is_featured=tpl.is_featured,
        use_count=tpl.use_count,
        created_by=tpl.created_by,
        org_id=tpl.org_id,
        created_at=tpl.created_at,
    )


async def list_templates(
    db: AsyncSession,
    *,
    org_id: str | None = None,
    visibility: str | None = None,
    keyword: str | None = None,
    featured_only: bool = False,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[InstanceTemplateInfo], int]:
    q = select(InstanceTemplate).where(not_deleted(InstanceTemplate), InstanceTemplate.is_published.is_(True))
    if visibility == "org_private":
        q = q.where(InstanceTemplate.visibility == "org_private", InstanceTemplate.org_id == org_id)
    elif visibility == "public":
        q = q.where(InstanceTemplate.visibility == "public")
    elif org_id:
        q = q.where(
            or_(InstanceTemplate.visibility == "public", and_(InstanceTemplate.visibility == "org_private", InstanceTemplate.org_id == org_id))
        )
    if keyword:
        like = f"%{keyword}%"
        q = q.where(InstanceTemplate.name.ilike(like) | InstanceTemplate.description.ilike(like))
    if featured_only:
        q = q.where(InstanceTemplate.is_featured.is_(True))

    count_q = select(func.count()).select_from(q.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    q = q.order_by(InstanceTemplate.use_count.desc(), InstanceTemplate.created_at.desc())
    q = q.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(q)
    templates = result.scalars().all()

    items_list = [_template_to_info(t) for t in templates]
    return items_list, total


async def get_template(db: AsyncSession, template_id: str, org_id: str | None = None) -> InstanceTemplateInfo:
    tpl = await _get_template_model(db, template_id, org_id)
    ti_list = await _get_template_items(db, template_id)
    if ti_list:
        item_refs = await _resolve_item_refs(db, ti_list)
        gene_slugs = [r.slug for r in item_refs if r.type == "gene"]
        genes = await _resolve_gene_refs(db, gene_slugs)
        return _template_to_info(tpl, genes, item_refs)

    slugs = _parse_gene_slugs(tpl.gene_slugs)
    genes = await _resolve_gene_refs(db, slugs)
    return _template_to_info(tpl, genes)


async def get_template_gene_slugs(
    db: AsyncSession, template_id: str, org_id: str | None = None,
) -> list[str]:
    tpl = await _get_template_model(db, template_id, org_id)
    ti_list = await _get_template_items(db, template_id)
    if not ti_list:
        return _parse_gene_slugs(tpl.gene_slugs)

    all_slugs: list[str] = []
    genome_slugs_to_expand = []
    for item in ti_list:
        if item.item_type == "gene":
            all_slugs.append(item.item_slug)
        else:
            genome_slugs_to_expand.append(item.item_slug)

    if genome_slugs_to_expand:
        res = await db.execute(
            select(Genome).where(Genome.slug.in_(genome_slugs_to_expand), not_deleted(Genome))
        )
        found_slugs: set[str] = set()
        for gm in res.scalars().all():
            found_slugs.add(gm.slug)
            try:
                expanded = json.loads(gm.gene_slugs or "[]")
                all_slugs.extend(expanded)
            except (json.JSONDecodeError, TypeError):
                logger.warning("Failed to parse gene_slugs for genome %s", gm.slug)
        missing = set(genome_slugs_to_expand) - found_slugs
        if missing:
            logger.warning("Genomes not found during expansion: %s", missing)

    seen: set[str] = set()
    deduped: list[str] = []
    for s in all_slugs:
        if s not in seen:
            seen.add(s)
            deduped.append(s)
    return deduped


async def get_template_agent_bundle_manifest(
    db: AsyncSession, template_id: str, org_id: str | None = None,
) -> dict[str, Any] | None:
    tpl = await _get_template_model(db, template_id, org_id)
    if tpl.template_type != InstanceTemplateType.agent_bundle:
        return None
    return _template_agent_bundle_manifest(tpl, include_platform_secret_source=True)


async def get_template_deploy_env_vars(
    db: AsyncSession,
    template_id: str,
    org_id: str | None = None,
    *,
    instance_id: str | None = None,
) -> dict[str, str]:
    tpl = await _get_template_model(db, template_id, org_id)
    if tpl.template_type != InstanceTemplateType.agent_bundle:
        return {}
    manifest = sanitize_agent_bundle_manifest(_parse_json_obj(tpl.agent_bundle_manifest))
    return build_bundle_env_vars(manifest, tpl.slug, instance_id=instance_id)


def _build_gene_slug(template_slug: str, skill_slug: str, org_id: str | None) -> str:
    org_fragment = normalize_bundle_slug(org_id or "global")[:8]
    base = normalize_bundle_slug(f"{template_slug}-{skill_slug}-{org_fragment}")
    return base[:128].rstrip("-")


def _build_gene_manifest(skill: dict[str, Any], files: dict[str, str], template_slug: str) -> dict[str, Any]:
    permissions = skill.get("permissions") if isinstance(skill.get("permissions"), dict) else {}
    tools = permissions.get("tools") if isinstance(permissions.get("tools"), list) else []
    manifest: dict[str, Any] = {
        "skill": {
            "name": skill["name"],
            "content": files.get(skill["path"], ""),
        },
        "agent_bundle": {
            "template_slug": template_slug,
            "skill_path": skill["path"],
        },
    }
    if tools:
        manifest["tool_allow"] = tools
    scripts = skill.get("scripts") if isinstance(skill.get("scripts"), dict) else {}
    if scripts:
        manifest["scripts"] = {
            Path(path).name: content
            for path, content in scripts.items()
        }
    return manifest


async def _create_agent_bundle_genes(
    db: AsyncSession,
    *,
    template_slug: str,
    manifest: dict[str, Any],
    user_id: str,
    org_id: str | None,
) -> list[str]:
    files = manifest.get("files") if isinstance(manifest.get("files"), dict) else {}
    gene_slugs: list[str] = []
    for skill in manifest.get("skills", []):
        if not isinstance(skill, dict):
            continue
        gene_slug = _build_gene_slug(template_slug, str(skill["slug"]), org_id)
        existing = await db.execute(
            select(Gene).where(
                Gene.slug == gene_slug,
                Gene.org_id == org_id,
                not_deleted(Gene),
            )
        )
        gene = existing.scalar_one_or_none()
        gene_manifest = _build_gene_manifest(skill, files, template_slug)
        if gene:
            gene.name = str(skill["name"])
            gene.description = str(skill.get("description") or "")
            gene.short_description = str(skill.get("description") or "")[:256]
            gene.version = str(skill.get("version") or "1.0.0")[:16]
            gene.manifest = json.dumps(gene_manifest, ensure_ascii=False)
            gene.source = GeneSource.agent
            gene.visibility = ContentVisibility.org_private
            gene.is_published = False
            gene.source_ref = f"agent_bundle:{template_slug}:{skill['name']}"
        else:
            db.add(Gene(
                name=str(skill["name"]),
                slug=gene_slug,
                description=str(skill.get("description") or ""),
                short_description=str(skill.get("description") or "")[:256],
                category="能力",
                tags=json.dumps(["agent_bundle", template_slug], ensure_ascii=False),
                source=GeneSource.agent,
                source_ref=f"agent_bundle:{template_slug}:{skill['name']}",
                version=str(skill.get("version") or "1.0.0")[:16],
                manifest=json.dumps(gene_manifest, ensure_ascii=False),
                dependencies="[]",
                synergies="[]",
                is_featured=False,
                is_published=False,
                created_by=user_id,
                org_id=org_id,
                visibility=ContentVisibility.org_private,
            ))
        gene_slugs.append(gene_slug)
    await db.flush()
    return gene_slugs


async def create_template(
    db: AsyncSession,
    req: InstanceTemplateCreate,
    user_id: str,
    org_id: str | None = None,
) -> InstanceTemplateInfo:
    existing = await db.execute(
        select(InstanceTemplate).where(
            InstanceTemplate.slug == req.slug,
            InstanceTemplate.org_id == org_id,
            not_deleted(InstanceTemplate),
        )
    )
    if existing.scalar_one_or_none():
        raise ConflictError(f"\u6a21\u677f slug '{req.slug}' \u5df2\u5b58\u5728")

    items_input = req.items
    if not items_input and req.gene_slugs:
        items_input = [TemplateItemInput(type="gene", slug=s) for s in req.gene_slugs]

    tpl = InstanceTemplate(
        name=req.name,
        slug=req.slug,
        description=req.description,
        short_description=req.short_description,
        icon=req.icon,
        gene_slugs=json.dumps([i.slug for i in items_input if i.type == "gene"]) if items_input else "[]",
        created_by=user_id,
        org_id=org_id,
    )
    db.add(tpl)
    await db.flush()

    if items_input:
        await _write_template_items(db, tpl.id, items_input)

    await db.commit()
    await db.refresh(tpl)

    ti_list = await _get_template_items(db, tpl.id)
    item_refs = await _resolve_item_refs(db, ti_list)
    gene_slugs = [r.slug for r in item_refs if r.type == "gene"]
    genes = await _resolve_gene_refs(db, gene_slugs)
    return _template_to_info(tpl, genes, item_refs)


async def import_agent_bundle_template(
    db: AsyncSession,
    req: AgentBundleImportRequest,
    user_id: str,
    org_id: str | None = None,
) -> InstanceTemplateInfo:
    manifest = parse_agent_bundle_dir(req.bundle_path)
    return await import_agent_bundle_manifest(
        db,
        manifest,
        user_id=user_id,
        org_id=org_id,
        name=req.name,
        slug=req.slug,
        description=req.description,
        short_description=req.short_description,
        icon=req.icon,
    )


async def import_agent_bundle_manifest(
    db: AsyncSession,
    manifest: dict[str, Any],
    *,
    user_id: str,
    org_id: str | None = None,
    name: str | None = None,
    slug: str | None = None,
    description: str | None = None,
    short_description: str | None = None,
    icon: str | None = None,
) -> InstanceTemplateInfo:
    template_slug = normalize_bundle_slug(slug or str(manifest["slug"]))

    existing = await db.execute(
        select(InstanceTemplate).where(
            InstanceTemplate.slug == template_slug,
            InstanceTemplate.org_id == org_id,
            not_deleted(InstanceTemplate),
        )
    )
    if existing.scalar_one_or_none():
        raise ConflictError(f"模板 slug '{template_slug}' 已存在")

    manifest["slug"] = template_slug
    gene_slugs = await _create_agent_bundle_genes(
        db,
        template_slug=template_slug,
        manifest=manifest,
        user_id=user_id,
        org_id=org_id,
    )
    items_input = [TemplateItemInput(type="gene", slug=s) for s in gene_slugs]

    template_name = (
        _clean_template_display_name(name)
        or _suggest_agent_bundle_display_name(manifest)
        or await _suggest_next_agent_bundle_display_name(db, org_id)
    )

    tpl = InstanceTemplate(
        name=template_name,
        slug=template_slug,
        description=description if description is not None else manifest.get("description"),
        short_description=short_description or manifest.get("description"),
        icon=icon or "package",
        gene_slugs=json.dumps(gene_slugs, ensure_ascii=False),
        template_type=InstanceTemplateType.agent_bundle,
        agent_bundle_manifest=json.dumps(manifest, ensure_ascii=False),
        bundle_storage_key=f"db://instance_templates/{template_slug}/agent_bundle_manifest",
        resource_recommendation=json.dumps(manifest.get("resource_recommendation"), ensure_ascii=False)
        if manifest.get("resource_recommendation") else None,
        upload_contract=json.dumps(manifest.get("upload_contract"), ensure_ascii=False)
        if manifest.get("upload_contract") else None,
        secret_refs=json.dumps(manifest.get("secret_refs") or [], ensure_ascii=False),
        created_by=user_id,
        org_id=org_id,
        visibility=ContentVisibility.org_private,
        is_published=True,
        is_featured=False,
    )
    db.add(tpl)
    await db.flush()
    await _write_template_items(db, tpl.id, items_input)

    await db.commit()
    await db.refresh(tpl)

    ti_list = await _get_template_items(db, tpl.id)
    item_refs = await _resolve_item_refs(db, ti_list)
    genes = await _resolve_gene_refs(db, gene_slugs)
    return _template_to_info(tpl, genes, item_refs)


async def create_from_instance(
    db: AsyncSession,
    instance_id: str,
    req: InstanceTemplateFromInstance,
    user_id: str,
    org_id: str | None = None,
) -> InstanceTemplateInfo:
    inst = await db.execute(
        select(Instance).where(
            Instance.id == instance_id,
            Instance.org_id == org_id,
            not_deleted(Instance),
        )
    )
    if not inst.scalar_one_or_none():
        raise NotFoundError("实例不存在")

    existing = await db.execute(
        select(InstanceTemplate).where(
            InstanceTemplate.slug == req.slug,
            InstanceTemplate.org_id == org_id,
            not_deleted(InstanceTemplate),
        )
    )
    if existing.scalar_one_or_none():
        raise ConflictError(f"\u6a21\u677f slug '{req.slug}' \u5df2\u5b58\u5728")

    ig_result = await db.execute(
        select(Gene.slug).join(InstanceGene, InstanceGene.gene_id == Gene.id).where(
            InstanceGene.instance_id == instance_id,
            InstanceGene.status == "installed",
            not_deleted(InstanceGene),
            not_deleted(Gene),
        )
    )
    gene_slugs = [row[0] for row in ig_result.all()]

    tpl = InstanceTemplate(
        name=req.name,
        slug=req.slug,
        description=req.description,
        short_description=req.short_description,
        icon=req.icon,
        gene_slugs=json.dumps(gene_slugs),
        source_instance_id=instance_id,
        created_by=user_id,
        org_id=org_id,
    )
    db.add(tpl)
    await db.flush()

    items_input = [TemplateItemInput(type="gene", slug=s) for s in gene_slugs]
    await _write_template_items(db, tpl.id, items_input)

    await db.commit()
    await db.refresh(tpl)

    ti_list = await _get_template_items(db, tpl.id)
    item_refs = await _resolve_item_refs(db, ti_list)
    genes = await _resolve_gene_refs(db, gene_slugs)
    return _template_to_info(tpl, genes, item_refs)


async def update_template(
    db: AsyncSession,
    template_id: str,
    req: InstanceTemplateUpdate,
    org_id: str | None = None,
) -> InstanceTemplateInfo:
    tpl = await _get_template_model(db, template_id, org_id, require_manage=True)
    if req.name is not None:
        cleaned_name = _clean_template_display_name(req.name)
        if not cleaned_name:
            raise BadRequestError("模板显示名称不能为空")
        tpl.name = cleaned_name
    if req.description is not None:
        tpl.description = req.description
    if req.short_description is not None:
        tpl.short_description = req.short_description
    if req.icon is not None:
        tpl.icon = req.icon

    items_input = req.items
    if items_input is None and req.gene_slugs is not None:
        items_input = [TemplateItemInput(type="gene", slug=s) for s in req.gene_slugs]

    if items_input is not None:
        await _soft_delete_template_items(db, template_id)
        await _write_template_items(db, template_id, items_input)
        tpl.gene_slugs = json.dumps([i.slug for i in items_input if i.type == "gene"])

    await db.commit()
    await db.refresh(tpl)

    ti_list = await _get_template_items(db, template_id)
    item_refs = await _resolve_item_refs(db, ti_list)
    gene_slugs = [r.slug for r in item_refs if r.type == "gene"]
    genes = await _resolve_gene_refs(db, gene_slugs)
    return _template_to_info(tpl, genes, item_refs)


async def delete_template(db: AsyncSession, template_id: str, org_id: str | None = None) -> dict:
    tpl = await _get_template_model(db, template_id, org_id, require_manage=True)
    await _soft_delete_template_items(db, template_id)
    tpl.soft_delete()
    await db.commit()
    return {"deleted": True}


async def increment_use_count(db: AsyncSession, template_id: str) -> None:
    result = await db.execute(
        select(InstanceTemplate).where(InstanceTemplate.id == template_id, not_deleted(InstanceTemplate))
    )
    tpl = result.scalar_one_or_none()
    if tpl:
        tpl.use_count = (tpl.use_count or 0) + 1
        await db.commit()
