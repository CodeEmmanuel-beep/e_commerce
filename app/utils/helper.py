from sqlalchemy import func, select, exists
from fastapi import HTTPException, Request
import uuid
from sqlalchemy.orm import selectinload
from werkzeug.utils import secure_filename
from app.logs.logger import get_logger
from app.models import store_owners, store_staffs, Inventory, Store, ProductVariant
from app.utils.redis import cache
from app.utils.supabase_url import cleaned_up
from app.database.config import settings
from io import BytesIO
from app.models import React
from app.api.v1.schemas import ReactionsSummary
from sqlalchemy.ext.asyncio import AsyncSession
import copy

logger = get_logger("helper")


def user_role(request: Request):
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="not authenticated")
    return user["role"]


def jwt_exp(request: Request):
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="not authenticated")
    return int(user["exp"])


def user_jti(request: Request):
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="not authenticated")
    return user["jti"]


def unique_id(request: Request):
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="not authenticated")
    return int(user["user_id"])


def unique_name(request: Request):
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="not authenticated")
    return user["sub"]


def deep_merge(d1, d2) -> dict:
    result = copy.deepcopy(d1)
    for k, v in d2.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = deep_merge(result[k], v)
        else:
            result[k] = v
    return result


async def react_summary(
    db: AsyncSession, r_id: list[int], db_schema, join_model, column_filter
) -> dict[int, ReactionsSummary]:
    if isinstance(r_id, int):
        r_id = [r_id]
    counts = (
        await db.execute(
            select(db_schema, React.reaction_type, func.count(React.id))
            .join(join_model, db_schema == join_model.id)
            .where(db_schema.in_(r_id), column_filter)
            .group_by(db_schema, React.reaction_type)
        )
    ).all()
    summary_map: dict[int, dict[str, int]] = {}
    for r_id_row, rtype, count in counts:
        key = rtype.name if hasattr(rtype, "name") else rtype
        summary_map.setdefault(r_id_row, {})[key] = count
    result: dict[int, ReactionsSummary] = {}
    for rid in r_id:
        summary = summary_map.get(rid, {})
        result[rid] = ReactionsSummary(
            like=summary.get("like", 0),
            love=summary.get("love", 0),
            laugh=summary.get("laugh", 0),
            angry=summary.get("angry", 0),
            wow=summary.get("wow", 0),
            sad=summary.get("sad", 0),
        )
    return result


async def upload_photo_helper(photo, request, get_supabase, bucket: str | None = None):
    user_id = unique_id(request)
    filename = None
    max_size = 5 * 1024 * 1024
    allowed_types = ("image/jpeg", "image/webp", "image/png")
    total_size = 0
    file_byte = b""
    if photo.content_type not in allowed_types:
        logger.warning(
            "user '%s', tried uploading an invalid file type: %s",
            user_id,
            photo.content_type,
        )
        raise HTTPException(
            status_code=400,
            detail="Invalid file type. Only JPG, PNG, WEBP allowed.",
        )
    filename = f"{uuid.uuid4()}_{secure_filename(photo.filename)}"
    try:
        with BytesIO() as buffer:
            while chunk := await photo.read(1024 * 1024):
                total_size += len(chunk)
                if total_size > max_size:
                    logger.warning(
                        "user: %s, tried uploading a file larger than file limit, file size '%s'",
                        user_id,
                        total_size,
                    )
                    raise HTTPException(
                        status_code=400, detail="File too large. Max 5MB."
                    )
                buffer.write(chunk)
            file_byte = buffer.getvalue()
            storage_bucket = bucket if bucket else settings.BUCKET
            logger.info(
                "user: %s, uploading photo: %s to bucket: %s",
                user_id,
                filename,
                storage_bucket,
            )
            upload_photo = await get_supabase.storage.from_(storage_bucket).upload(
                filename, file_byte, {"content-type": photo.content_type}
            )
            if hasattr(upload_photo, "error"):
                logger.error("error uploading photo %s", upload_photo)
                raise HTTPException(status_code=500, detail="error uploading photo")
            logger.info("user: %s, successfully uploaded photo: %s", user_id, filename)
            return filename
    except HTTPException:
        if filename:
            await cleaned_up(
                get_supabase,
                filename,
                context_1="error removing orphaned photo",
                context_2="successfully removed orphaned photo",
            )
        raise
    except Exception:
        logger.exception("error saving photo")
        if filename:
            await cleaned_up(
                get_supabase,
                filename,
                context_1="error removing orphaned photo",
                context_2="successfully removed orphaned photo",
            )
        raise HTTPException(status_code=500, detail="error saving photo")


async def pre_file_generator(file, user_id):
    total_size = 0
    max_image_size = 5 * 1024 * 1024
    while chunk := await file.read(1024 * 1024):
        total_size += len(chunk)
        if total_size > max_image_size:
            logger.warning(
                "user: %s, tried uploading an image larger than the max size approved, image size attempted: %s",
                user_id,
                total_size,
            )
            raise HTTPException(
                status_code=400, detail="image should not be more than 5mb"
            )
        yield chunk


async def file_generator(file, user_id):
    buffer = bytearray()
    async for chunk in pre_file_generator(file, user_id):
        buffer.extend(chunk)
        return bytes(buffer)


async def store_auth(store_id, db, request):
    user_id = unique_id(request)
    if not user_id:
        logger.warning("unauthorized attempt")
        raise HTTPException(status_code=401, detail="not authenticated")
    auth_stmt = select(
        exists().where(
            store_owners.c.stores_id == store_id, store_owners.c.users_id == user_id
        ),
        exists().where(
            store_staffs.c.stores_id == store_id, store_staffs.c.users_id == user_id
        ),
    )
    auth_result = (await db.execute(auth_stmt)).fetchone()
    owner_exist, staff_exist = auth_result if auth_result else (False, False)
    if not owner_exist and not staff_exist:
        logger.warning(
            "user: %s, made an ineligible attempt for store: %s",
            user_id,
            store_id,
        )
        raise HTTPException(status_code=403, detail="ineligible credentials")
    return user_id


def store_inventory(store_id, inventory_id: int | None = None):
    base_filter = [
        Inventory.store_id == store_id,
        Inventory.is_deleted.is_(False),
        ProductVariant.is_deleted.is_(False),
    ]
    if inventory_id:
        base_filter.append(Inventory.id == inventory_id)
        stmt = (
            select(Inventory)
            .join(ProductVariant, Inventory.variant_id == ProductVariant.id)
            .options(selectinload(Inventory.variant))
            .where(*base_filter)
        )
    else:
        stmt = (
            select(Inventory)
            .join(ProductVariant, Inventory.variant_id == ProductVariant.id)
            .options(selectinload(Inventory.variant))
            .where(*base_filter)
        )
    return stmt


def restore_inventory(order):
    for orderitems in order.orderitems:
        if orderitems.variant and orderitems.variant.inventory:
            stock = orderitems.variant.inventory
            stock.stock_quantity += orderitems.quantity
            if orderitems.variant.product.product_availability == "out_of_stock":
                orderitems.variant.product.product_availability = "available"


async def view_performance_helper(
    slug,
    context,
    db,
    request,
    context_1: str | None = None,
    context_2: str | None = None,
):
    user_id = unique_id(request)
    if not user_id:
        logger.warning(f"unauthorized attempt at the {context} endpoint")
        raise HTTPException(status_code=401, detail="unauthorized access")
    row = (
        await db.execute(
            select(
                Store,
                exists().where(
                    store_owners.c.users_id == user_id,
                    store_owners.c.stores_id == Store.id,
                ),
            ).where(
                Store.slug == slug,
                Store.approved.is_(True),
            )
        )
    ).fetchone()
    target_store, is_owner = row or (None, None)
    if not target_store or not is_owner:
        logger.warning(
            "user %s attempted to access %s for store %s without permission or store not found",
            user_id,
            context,
            slug,
        )
        raise HTTPException(status_code=403, detail="restricted access")
    if context_1 and context_2:
        cache_key = f"{slug}:{context}:{context_1}:{context_2}"
    elif context_1:
        cache_key = f"{slug}:{context}:{context_1}"
    else:
        cache_key = f"{context}:{slug}"
    cached_data = await cache(cache_key)
    if cached_data:
        logger.info(f"cache hit at the {context} endpoint for store: %s", slug)
        return cached_data
    return cache_key, target_store
