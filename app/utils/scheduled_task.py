from app.models import (
    Order,
    ProductVariant,
    OrderItem,
    OrderStatus,
    Membership,
    Subscription,
    SubscriptionStatus,
)
from app.database.async_config import AsyncSessionLocal, engine
from sqlalchemy import select, or_, cast, String
from sqlalchemy.orm import selectinload
from datetime import timedelta, datetime, timezone
from app.logs.logger import get_logger
import asyncio
from app.utils.helper import restore_inventory
from celery.signals import worker_process_init
from celery import shared_task

logger = get_logger("celery")


async def invalidate_order():
    async with AsyncSessionLocal() as session:
        now = datetime.now(timezone.utc)
        time_limit = now - timedelta(hours=1)
        retry_limit = now - timedelta(minutes=30)
        try:
            stmt = (
                select(Order)
                .options(
                    selectinload(Order.orderitems)
                    .selectinload(OrderItem.variant)
                    .options(
                        selectinload(ProductVariant.inventory),
                        selectinload(ProductVariant.product),
                    )
                )
                .where(
                    or_(
                        Order.created_at <= time_limit,
                        Order.re_order_time <= retry_limit,
                    ),
                    ~Order.order_delete,
                    Order.status == OrderStatus.pending,
                )
                .limit(1000)
                .with_for_update(skip_locked=True)
            )
            result = await session.execute(stmt)
            row = result.scalars().all()
            if not row:
                logger.info("No expired orders found for invalidation.")
                return
            processed_orders = []
            for order in row:
                if order.re_order_time and order.re_order_time <= retry_limit:
                    logger.info("preparing to invalidate order")
                    order.status = OrderStatus.cancelled
                    order.order_delete = True
                    if order.orderitems:
                        restore_inventory(order)
                        processed_orders.append(order.id)
                elif not order.re_order_time:
                    logger.info("preparing to invalidate order")
                    order.status = OrderStatus.cancelled
                    if order.orderitems:
                        restore_inventory(order)
                        processed_orders.append(order.id)
                else:
                    continue
            if not processed_orders:
                logger.info("No expired orders found for invalidation.")
                return
            await session.commit()
            for order_id in processed_orders:
                logger.info("Order with id: %s invalidated successfully", order_id)
            logger.info("Batch order invalidated successfully")
        except Exception:
            await session.rollback()
            logger.exception(
                "fatal processing exception occurred during batch order invalidation"
            )
            raise


async def activate():
    async with AsyncSessionLocal() as db:
        now = datetime.now(timezone.utc)
        try:
            activation = (
                await db.execute(
                    select(Membership, Subscription)
                    .join(Subscription, Membership.id == Subscription.membership_id)
                    .where(
                        Subscription.expire_at > now,
                        or_(
                            Subscription.status != SubscriptionStatus.active,
                            Membership.is_active.is_(False),
                        ),
                    )
                    .limit(1000)
                    .with_for_update(skip_locked=True)
                )
            ).all()
            if not activation:
                logger.info("no membership to reconcile")
                return
            for member, subscribe in activation:
                logger.info("activation process started")
                member.is_active = True
                subscribe.status = SubscriptionStatus.active
            await db.commit()
            logger.info("batched activation complete")
        except Exception:
            await db.rollback()
            logger.exception("fatal error, reconciling activation status")
            raise


async def deactivate():
    async with AsyncSessionLocal() as db:
        now = datetime.now(timezone.utc)
        try:
            deactivation = (
                await db.execute(
                    select(Membership, Subscription)
                    .join(Subscription, Membership.id == Subscription.membership_id)
                    .where(
                        Subscription.status != SubscriptionStatus.inactive,
                        Subscription.expire_at < now,
                    )
                    .limit(1000)
                    .with_for_update(skip_locked=True)
                )
            ).all()
            if not deactivation:
                logger.info("no membership to reconcile")
                return
            for member, subscribe in deactivation:
                logger.info("deactivation process started")
                member.is_active = False
                subscribe.status = SubscriptionStatus.past_due
            await db.commit()
            logger.info("batched deactivation complete")
        except Exception:
            await db.rollback()
            logger.exception("fatal error, reconciling deactivation status")
            raise


async def update_membership_type():
    async with AsyncSessionLocal() as db:
        try:
            member_update = (
                await db.execute(
                    select(Membership, Subscription)
                    .join(Subscription, Membership.id == Subscription.membership_id)
                    .where(
                        cast(Subscription.plan_name, String)
                        != cast(Membership.membership_type, String)
                    )
                    .limit(1000)
                    .with_for_update(skip_locked=True)
                )
            ).all()
            if not member_update:
                logger.info("no membership_type to reconcile")
                return
            for member, subscribe in member_update:
                logger.info("membership update started")
                member.membership_type = subscribe.plan_name
            await db.commit()
            logger.info("batched member update complete")
        except Exception:
            await db.rollback()
            logger.exception("fatal error, updating membership type")
            raise


def get_worker_loop(coro):
    try:
        loop = asyncio.get_running_loop()
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        return future.result()
    except RuntimeError:
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)


@worker_process_init.connect
def set_up_worker_process(**kwargs):
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(engine.dispose())
    except Exception:
        logger.exception("Failed to safely detach parent process database engine pool.")
    logger.info("worker process database engine reset complete.")


@shared_task(
    name="membership_update",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3, "countdown": 60},
)
def membership_update():
    try:
        get_worker_loop(update_membership_type())
    except Exception:
        logger.exception("fatal error, updating membership type")
        raise


@shared_task(
    name="member_subscribe_activation",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 5, "countdown": 20},
)
def activation_status():
    try:
        get_worker_loop(activate())
    except Exception:
        logger.exception("fatal error, reconciling activation status")
        raise


@shared_task(
    name="member_deactivation",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 5, "countdown": 20},
)
def deactivation_status():
    try:
        get_worker_loop(deactivate())
    except Exception:
        logger.exception("fatal error, reconciling activation status")
        raise


@shared_task(
    name="app.utils.scheduled_task.cancel_order",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 5, "countdown": 10},
)
def cancel_order():
    try:
        get_worker_loop(invalidate_order())
    except Exception:
        logger.exception(
            "fatal processing exception occurred during batch order invalidation"
        )
        raise
