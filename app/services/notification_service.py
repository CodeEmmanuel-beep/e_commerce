from sse_starlette.sse import EventSourceResponse
from fastapi import HTTPException
from app.utils.redis import notifications_stream
from app.models import Notification, User
from app.logs.logger import get_logger
from sqlalchemy.orm import selectinload
from app.api.v1.schemas import (
    NotificationResponse,
    PaginatedMetadata,
    StandardResponse,
    PaginatedResponse,
)
from app.utils.redis import cache, cached, notification_invalidation
from app.utils.helper import unique_id
from sqlalchemy import select, func, update

logger = get_logger("notifications")


async def notification_stream(request):
    user_id = unique_id(request)
    if not user_id:
        logger.warning("unauthorized attempt at notice endpoint")
        raise HTTPException(status_code=401, detail="unauthorized access")
    await notification_invalidation(user_id)
    try:
        return EventSourceResponse(notifications_stream(user_id))
    except Exception:
        logger.exception("SSE stream failed for user %s", user_id)
        raise HTTPException(status_code=500, detail="stream error")


async def retrieve_notifications(
    db,
    request,
):
    user_id = unique_id(request)
    if not user_id:
        logger.warning("unauthorized attempt at get_notifications endpoint")
        raise HTTPException(status_code=401, detail="unauthorized access")
    notification_key = f"notification:{user_id}"
    cached_data = await cache(notification_key)
    if cached_data:
        logger.info(f"Cache hit at the get_notification endpoint for user {user_id}")
        return StandardResponse(**cached_data)
    notifier = (
        await db.execute(
            select(Notification, User)
            .outerjoin(User, Notification.from_user == User.id)
            .options(
                selectinload(Notification.product),
                selectinload(Notification.productvariant),
                selectinload(Notification.store),
            )
            .where(Notification.notified_user == user_id)
            .order_by(Notification.created_at.desc())
            .limit(30)
        )
    ).all()
    if not notifier:
        logger.error("user %s, attempt to fetch notifications returned null", user_id)
        return StandardResponse(
            status="success", message="no notification found", data=None
        )
    items = []
    for notify, sender in notifier:
        data = NotificationResponse.model_validate(notify)
        if notify.product_id:
            data.product_name = (
                notify.product.product_name
                if notify.product.id == notify.product_id
                else None
            )
        if notify.variant_id:
            data.sku = (
                notify.productvariant.sku
                if notify.productvariant.id == notify.variant_id
                else None
            )
        data.store_name = (
            notify.store.store_name if notify.store.id == notify.store_id else None
        )
        if notify.notification.startswith("replied"):
            data.notification = (
                f"{sender.first_name} {sender.surname} {notify.notification}"
                if sender.is_active
                else f"{notify.notification} by deleted user"
            )
        elif notify.notification.startswith("you"):
            data.notification = notify.notification
        else:
            data.notification = (
                f"{notify.notification} by {sender.first_name} {sender.surname}"
                if sender.is_active
                else f"{notify.notification} by deleted user"
            )
        items.append(data)
    await db.execute(
        update(Notification)
        .where(Notification.notified_user == user_id)
        .values(is_read=True)
    )
    await db.commit()
    full_data = StandardResponse(status="success", message="notifications", data=items)
    await cached(notification_key, full_data, ttl=60)
    logger.info(f"notification data cached for user {user_id}")
    return full_data


async def notifications_list(page, limit, db, request):
    user_id = unique_id(request)
    if not user_id:
        logger.warning("unauthorized attempt at get_notifications endpoint")
        raise HTTPException(status_code=401, detail="unauthorized access")
    offset = (page - 1) * limit
    notification_key = f"notification:{user_id}:{page}:{limit}"
    cached_data = await cache(notification_key)
    if cached_data:
        logger.info(f"Cache hit at the get_notification endpoint for user {user_id}")
        return StandardResponse(**cached_data)
    notifier = (
        await db.execute(
            select(Notification, User)
            .outerjoin(User, Notification.from_user == User.id)
            .options(
                selectinload(Notification.product),
                selectinload(Notification.productvariant),
                selectinload(Notification.store),
            )
            .where(Notification.notified_user == user_id)
            .order_by(Notification.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
    ).all()
    if not notifier:
        logger.error("user %s, attempt to fetch notifications returned null", user_id)
        return StandardResponse(
            status="success", message="no notification found", data=None
        )
    total = (
        await db.execute(
            select(func.count(Notification.id)).where(
                Notification.notified_user == user_id
            )
        )
    ).scalar() or 0
    logger.info("total number of notifications for user %s is %s", user_id, total)
    items = []
    for notify, sender in notifier:
        data = NotificationResponse.model_validate(notify)
        if notify.product_id:
            data.product_name = (
                notify.product.product_name
                if notify.product.id == notify.product_id
                else None
            )
        if notify.variant_id:
            data.sku = (
                notify.productvariant.sku
                if notify.productvariant.id == notify.variant_id
                else None
            )
        data.store_name = (
            notify.store.store_name if notify.store.id == notify.store_id else None
        )
        if notify.notification.startswith("replied"):
            data.notification = (
                f"{sender.first_name} {sender.surname} {notify.notification}"
                if sender.is_active
                else f"{notify.notification} by deleted user"
            )
        elif notify.notification.startswith("you"):
            data.notification = notify.notification
        else:
            data.notification = (
                f"{notify.notification} by {sender.first_name} {sender.surname}"
                if sender.is_active
                else f"{notify.notification} by deleted user"
            )
        items.append(data)
    await db.execute(
        update(Notification)
        .where(Notification.notified_user == user_id)
        .values(is_read=True)
    )
    await db.commit()
    data = PaginatedMetadata[NotificationResponse](
        items=items,
        pagination=PaginatedResponse(page=page, limit=limit, total=total),
    )
    full_data = StandardResponse(status="success", message="notifications", data=data)
    await cached(notification_key, full_data, ttl=60)
    logger.info(f"notification data cached for user {user_id}")
    return full_data
