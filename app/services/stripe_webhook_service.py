import stripe
from app.database.config import settings
from fastapi import HTTPException
from datetime import datetime, timezone
from app.database.async_config import AsyncSessionLocal
from sqlalchemy import literal, update, case, func, text, or_, cast
from sqlalchemy.exc import IntegrityError
from app.models import (
    Subscription,
    Membership,
    SubscriptionStatus,
    SubscriptionPlan,
    Order,
    Payment,
    PaymentStatus,
    Refund,
    OrderStatus,
)
from app.logs.logger import get_logger
from app.services.payment_service import membership_activation

logger = get_logger("stripe_webhook")
target_enum = Payment.payment_status.type


async def stripe_webhook(request, background_task):
    payload = await request.body()
    sig_header = request.headers.get("Stripe-Signature")
    event = None
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
        )
    except Exception:
        logger.exception("error verifying signature")
        raise HTTPException(status_code=400, detail="invalid signature")
    membership_id = None
    user_id = None
    session = event["data"]["object"]
    stripe_session_id = getattr(session, "id", None)
    created_at = getattr(session, "created", None)
    created_timestamp = (
        datetime.fromtimestamp(created_at, tz=timezone.utc)
        if created_at
        else datetime.now(timezone.utc)
    )
    invoice_metadata = None
    invoice_metadata_type = None
    metadata = getattr(session, "metadata", None)
    type_metadata = getattr(metadata, "type", None)
    sub_details = getattr(session, "subscription_details", {})
    subscription_metadata = getattr(sub_details, "metadata", {})
    type_subscription_metadata = getattr(subscription_metadata, "type", None)
    parent_data = getattr(session, "parent", {})
    sub_detailed = getattr(parent_data, "subscription_details", {})
    invoice_metadata = getattr(sub_detailed, "metadata", {})
    invoice_metadata_type = getattr(invoice_metadata, "type", {})
    if not invoice_metadata:
        line_data = getattr(session, "lines", {})
        lines_list = getattr(line_data, "data", {})
        if lines_list and len(lines_list) > 0:
            first_line = lines_list[0]
            invoice_metadata = getattr(first_line, "metadata", {})
            invoice_metadata_type = getattr(invoice_metadata, "type", {})
    VALID_SUCCESS_EVENTS = (
        "checkout.session.completed",
        "payment_intent.succeeded",
        "charge.succeeded",
    )
    VALID_FAILURE_EVENTS = (
        "checkout.session.expired",
        "payment_intent.payment_failed",
        "charge.failed",
    )
    ORDER_PAYMENT_EVENTS = (
        "checkout.session.completed",
        "payment_intent.succeeded",
        "charge.succeeded",
        "checkout.session.expired",
        "payment_intent.payment_failed",
        "charge.failed",
    )
    detected_types = [type_metadata, type_subscription_metadata, invoice_metadata_type]
    is_membership = "membership" in detected_types and event["type"] not in (
        "invoice.paid",
        "invoice.created",
        "charge.updated",
        "invoice.finalized",
    )
    is_order_payment = type_metadata == "order_payment" and event["type"] in (
        ORDER_PAYMENT_EVENTS
    )
    is_order_refund = type_metadata in ("order_refund", "order_payment") and event[
        "type"
    ] in (
        "charge.refunded",
        "refund.updated",
    )
    if event["type"] == "invoice.upcoming":
        logger.info(
            f"Received invoice.upcoming preview for subscription {invoice_metadata}:{subscription_metadata} . No action required."
        )
        return {"status": "ignored"}
    if not any([is_membership, is_order_payment, is_order_refund]):
        logger.warning(
            f"Received unhandled payload category. Event: {event['type']}, Metadata: {metadata}"
        )
        return {"status": "ignored", "message": "Event type not tracked"}
    async with AsyncSessionLocal() as db:
        if is_membership:
            logger.info(
                f"Received webhook for membership subscription event: {event['type']} with metadata: {metadata}| {invoice_metadata}"
            )
            membership_id_str = getattr(metadata, "membership_id", None) or getattr(
                invoice_metadata, "membership_id", None
            )
            sub_id = getattr(session, "subscription", None)
            membership_id = int(membership_id_str) if membership_id_str else None
            user_id_str = getattr(metadata, "user_id", None) or getattr(
                invoice_metadata, "user_id", None
            )
            user_id = int(user_id_str) if user_id_str else None
            payment_type = getattr(metadata, "payment_type", None) or getattr(
                invoice_metadata, "payment_type", None
            )
            if not sub_id:
                sub_id = stripe_session_id
            event_type = literal(event["type"])
            subscription_days = None
            update_price = None
            update_product = None
            if event["type"].startswith("customer.subscription"):
                sub_items = (
                    getattr(session, "items", None)
                    if hasattr(session, "items")
                    else session.get("items")
                )
                if sub_items:
                    item_data = (
                        getattr(sub_items, "data", [])
                        if hasattr(sub_items, "data")
                        else sub_items.get("data")
                    )
                    if item_data:
                        first_data = item_data[0]
                        subscription_days = (
                            getattr(first_data, "current_period_end")
                            if hasattr(first_data, "current_period_end")
                            else first_data.get("current_period_end")
                        )
            elif event["type"].startswith("invoice"):
                lines = getattr(session, "lines", {})
                if lines:
                    lines_data = (
                        getattr(lines, "data", [])
                        if hasattr(lines, "data")
                        else lines.get("data")
                    )
                    second_data = None
                    if lines_data:
                        first_data = lines_data[0]
                        if len(lines_data) > 1:
                            second_data = lines_data[1]
                        line_period = (
                            getattr(first_data, "period", {})
                            if hasattr(first_data, "period")
                            else first_data.get("period")
                        )
                        if line_period:
                            subscription_days = (
                                getattr(line_period, "end")
                                if hasattr(line_period, "end")
                                else line_period.get("end")
                            )
                        target_data = second_data if second_data else first_data
                        line_price = getattr(target_data, "pricing", {})
                        price_details = getattr(line_price, "price_details", {})
                        if price_details:
                            product_id = (
                                getattr(price_details, "product", None)
                                if hasattr(price_details, "product")
                                else price_details.get("product")
                            )
                            price_id = (
                                getattr(price_details, "price", None)
                                if hasattr(price_details, "price")
                                else price_details.get("price")
                            )
                            update_product = product_id
                            update_price = price_id
            if not subscription_days:
                subscription_days = getattr(session, "period_end", None)
            if event["type"] == "customer.subscription.updated":
                sub_items = getattr(session, "items", None)
                if sub_items:
                    item_data = (
                        getattr(sub_items, "data", [])
                        if hasattr(sub_items, "data")
                        else sub_items.get("data")
                    )
                    if item_data:
                        first_data = item_data[0]
                        data_price = (
                            getattr(first_data, "price", None)
                            if hasattr(first_data, "price")
                            else first_data.get("price")
                        )
                        if data_price:
                            product_price = (
                                getattr(data_price, "id")
                                if hasattr(data_price, "id")
                                else data_price.get("id")
                            )
                            product_id = (
                                getattr(data_price, "product")
                                if hasattr(data_price, "product")
                                else data_price.get("product")
                            )
                        update_product = product_id
                        update_price = product_price
            expire_case = case(
                (
                    event_type.in_(
                        ("checkout.session.completed", "payment_intent.succeeded")
                    ),
                    func.greatest(Subscription.expire_at, func.now())
                    + text("INTERVAL '30 days'"),
                ),
                (
                    event_type.in_(
                        (
                            "customer.subscription.updated",
                            "invoice.payment_succeeded",
                        )
                    ),
                    func.to_timestamp(subscription_days),
                ),
                else_=Subscription.expire_at,
            )
            status_case = case(
                (
                    event_type.in_(
                        (
                            "checkout.session.completed",
                            "invoice.payment_succeeded" "payment_intent.succeeded",
                        )
                    ),
                    SubscriptionStatus.active,
                ),
                (
                    event_type == "customer.subscription.deleted",
                    SubscriptionStatus.cancelled,
                ),
                (
                    event_type.in_(
                        (
                            "invoice.payment_failed",
                            "checkout.session.expired",
                        )
                    ),
                    SubscriptionStatus.past_due,
                ),
                else_=Subscription.status,
            )
            reference_id = Subscription.reference_id
            if payment_type == "one_time":
                reference_id = case(
                    (
                        event_type.in_(
                            ("checkout.session.completed", "checkout.session.expired")
                        ),
                        getattr(session, "payment_intent", None),
                    ),
                    (
                        event_type.in_(
                            (
                                "payment_intent.payment_failed",
                                "payment_intent.succeeded",
                            )
                        ),
                        getattr(session, "id", None),
                    ),
                    (
                        event_type == "customer.subscription.deleted",
                        getattr(session, "subscription", None),
                    ),
                    else_=Subscription.reference_id,
                )
            elif payment_type == "subscription":
                reference_id = case(
                    (
                        event_type.in_(
                            (
                                "checkout.session.completed",
                                "checkout.session.expired",
                                "customer.subscription.deleted",
                            )
                        ),
                        getattr(session, "subscription", None),
                    ),
                    (
                        event_type.in_(
                            (
                                "invoice.payment_failed",
                                "invoice.payment_succeeded",
                            )
                        ),
                        getattr(session, "id", None),
                    ),
                    else_=Subscription.reference_id,
                )
            membership_status_case = case(
                (
                    event_type.in_(
                        (
                            "checkout.session.completed",
                            "invoice.payment_succeeded",
                            "payment_intent.succeeded",
                        )
                    ),
                    True,
                ),
                else_=Membership.is_active,
            )
            update_values = {
                "last_event_id": event["id"],
                "customer_id": getattr(session, "customer", None)
                or Subscription.customer_id,
                "expire_at": expire_case,
                "status": status_case,
                "reference_id": reference_id,
                "last_event_at": created_timestamp,
            }
            if (
                event["type"]
                in (
                    "customer.subscription.updated",
                    "invoice.payment_succeeded",
                )
                and update_product is not None
            ):
                product_value = {
                    settings.Standard_Product: SubscriptionPlan.Standard,
                    settings.Regular_Product: SubscriptionPlan.Regular,
                    settings.Premium_Product: SubscriptionPlan.Premium,
                }
                update_values["plan_name"] = product_value[update_product]
                update_values["price_id"] = update_price
            if membership_id:
                idem = await db.execute(
                    update(Subscription)
                    .where(
                        Subscription.membership_id == membership_id,
                        or_(
                            Subscription.last_event_at.is_(None),
                            Subscription.last_event_at <= created_timestamp,
                        ),
                        or_(
                            Subscription.last_event_id.is_(None),
                            Subscription.last_event_id != event["id"],
                        ),
                    )
                    .values(**update_values)
                    .returning(Subscription.membership_id)
                )
                returned_ids = idem.scalars().all()
                if not returned_ids:
                    logger.info(
                        f"Subscription {membership_id} of event_id: {event['id']} already processed. Skipping."
                    )
                    return {"status": "success", "message": "already processed"}
                idempo = await db.execute(
                    update(Membership)
                    .where(Membership.id.in_(returned_ids))
                    .values(is_active=membership_status_case)
                )
            else:
                logger.error(
                    f"Membership event {event['id']} received but missing a valid membership_id in metadata."
                )
                return {"status": "error", "message": "missing membership_id"}
        elif is_order_payment:
            logger.info(
                f"Received webhook for order payment event: {event['type']} with metadata: {metadata}"
            )
            if event["type"].startswith("checkout.session."):
                actual_transaction_id = getattr(session, "payment_intent", None)
            else:
                actual_transaction_id = getattr(session, "id", None)
            event_type = literal(event["type"])
            payment_status_case = case(
                (
                    event_type.in_(VALID_SUCCESS_EVENTS),
                    cast(PaymentStatus.SUCCESS.value, target_enum),
                ),
                (
                    event_type.in_(VALID_FAILURE_EVENTS),
                    cast(PaymentStatus.FAILED.value, target_enum),
                ),
                else_=Payment.payment_status,
            )
            if event["type"] in VALID_SUCCESS_EVENTS:
                order_status = OrderStatus.processing
            else:
                order_status = OrderStatus.pending
            transaction_id_case = case(
                (event_type.in_(VALID_SUCCESS_EVENTS), actual_transaction_id),
                (
                    event_type.in_(VALID_FAILURE_EVENTS),
                    actual_transaction_id,
                ),
                else_=Payment.transaction_id,
            )
            order_id = (
                int(metadata["order_id"])
                if metadata and "order_id" in metadata
                else None
            )
            if order_id:
                idemp = await db.execute(
                    update(Payment)
                    .where(
                        or_(
                            Payment.reference_id == stripe_session_id,
                            Payment.order_id == order_id,
                        ),
                        or_(
                            Payment.last_event_at.is_(None),
                            Payment.last_event_at <= created_timestamp,
                        ),
                        or_(
                            Payment.last_event_id.is_(None),
                            Payment.last_event_id != event["id"],
                        ),
                    )
                    .values(
                        last_event_id=event["id"],
                        last_event_at=created_timestamp,
                        transaction_id=transaction_id_case,
                        payment_status=payment_status_case,
                    )
                    .returning(Payment.order_id)
                )
                rows = idemp.scalars().all()
                if not rows:
                    logger.info(
                        f"Payment {stripe_session_id} already processed. Skipping."
                    )
                    return {"status": "success", "message": "already processed"}
                await db.execute(
                    update(Order)
                    .where(Order.id.in_(rows))
                    .values(status=order_status, reference_id=actual_transaction_id)
                    .returning(Order.id)
                )
        elif is_order_refund:
            logger.info(
                f"Received webhook for order payment event: {event['type']} with metadata: {metadata}"
            )
            if event["type"] == "charge.refunded":
                refunds_obj = getattr(session, "refunds", {})
                if refunds_obj:
                    refunds_list = (
                        getattr(refunds_obj, "data", [])
                        if hasattr(refunds_obj, "data")
                        else refunds_obj.get("data", [])
                    )
                    if refunds_list:
                        stripe_session_id = (
                            getattr(refunds_list[-1], "id", None)
                            if hasattr(refunds_list[-1], "id")
                            else refunds_list[-1].get("id")
                        )
            target_status = PaymentStatus.REFUNDED.value
            if (
                getattr(session, "object", None) == "refund"
                and getattr(session, "status", None) == "failed"
            ):
                target_status = PaymentStatus.SUCCESS.value
                logger.error(
                    f"Bank rejected refund {stripe_session_id}. Reverting parent payment status."
                )
            idempo = await db.execute(
                update(Refund)
                .where(
                    Refund.refund_id == stripe_session_id,
                    or_(
                        Refund.last_event_at.is_(None),
                        Refund.last_event_at <= created_timestamp,
                    ),
                    or_(
                        Refund.last_event_id.is_(None),
                        Refund.last_event_id != event["id"],
                    ),
                )
                .values(last_event_id=event["id"], last_event_at=created_timestamp)
                .returning(Refund.payment_id)
            )
            refunded = idempo.scalar_one_or_none()
            if not refunded:
                logger.info(f"Payment {stripe_session_id} already processed. Skipping.")
                return {"status": "success", "message": "already processed"}
            payment_id = int(refunded)
            await db.execute(
                update(Payment)
                .where(Payment.id == payment_id)
                .values(payment_status=cast(target_status, target_enum))
            )
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            logger.error(
                "database error while saving expired payment status on webhook endpoint"
            )
            raise HTTPException(status_code=400, detail="database error")
        except Exception:
            await db.rollback()
            logger.exception(
                "error while saving expired payment status on webhook endpoint"
            )
            raise HTTPException(status_code=500, detail="internal server error")
        logger.info(f"Payment {stripe_session_id} processed successfully.")
        if membership_id:
            background_task.add_task(membership_activation, membership_id, user_id)
        return {
            "status": "success",
            "message": "webhook payment processed",
        }
