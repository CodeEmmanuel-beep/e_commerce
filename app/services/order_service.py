from app.api.v1.schemas import (
    OrderResponse,
    PaginatedMetadata,
    CursorPaginatedResponse,
    PaginatedResponse,
    StandardResponse,
    OrderItemRes,
)
from app.models import (
    Store,
    Cart,
    Order,
    OrderItem,
    CartItem,
    Product,
    Inventory,
    OrderStatus,
    Membership,
    Payment,
    ProductVariant,
    PaymentStatus,
)
from datetime import datetime, timezone, timedelta
from fastapi import HTTPException
from app.logs.logger import get_logger
from sqlalchemy import select, func, update, exists
from sqlalchemy.orm import selectinload, joinedload
from sqlalchemy.exc import IntegrityError
from app.utils.redis import (
    cache,
    cached,
    order_global_invalidation,
    cart_invalidation,
    cache_version,
)
from app.utils.helper import restore_inventory, unique_id, store_auth
from decimal import Decimal

logger = get_logger("order")


async def order_expiration(store_id, order_id, db, request):
    user_id = unique_id(request)
    if not user_id:
        logger.warning("Unauthorized attempt at the order_expiration endpoint")
        raise HTTPException(status_code=401, detail="unauthorized access")
    stmt = select(Order).where(
        Order.order_delete.is_(False),
        Order.id == order_id,
        Order.store_id == store_id,
        Order.user_id == user_id,
    )
    order = (await db.execute(stmt)).scalar_one_or_none()
    if not order:
        logger.warning("order: '%s' not found", order_id)
        raise HTTPException(status_code=404, detail="order not found")
    now = datetime.now(timezone.utc)
    if order.re_order_time:
        delta = order.re_order_time + timedelta(minutes=30)
    else:
        delta = order.created_at + timedelta(hours=1)
    count_down = (delta - now).total_seconds()
    if order.status == OrderStatus.cancelled:
        data = {"total seconds remaining": 0, "order expires in": "0 seconds"}
        return StandardResponse(status="success", message="order expired", data=data)
    if count_down <= 0:
        data = {"total seconds remaining": 0, "order expires in": "0 seconds"}
        return StandardResponse(status="success", message="order expired", data=data)
    minutes = int(count_down // 60)
    seconds = int(count_down % 60)
    data = None
    if minutes > 1:
        data = {
            "total seconds remaining": int(count_down),
            "order expires in": f"{minutes} minutes and {seconds} seconds",
        }
    elif minutes == 1:
        data = {
            "total seconds remaining": int(count_down),
            "order expires in": f"{minutes} minute and {seconds} seconds",
        }
    elif minutes < 1:
        data = {
            "total seconds remaining": int(count_down),
            "order expires in": f"{seconds} seconds",
        }
    return StandardResponse(status="success", message="order active", data=data)


DISCOUNT_MAP = {
    "Standard": Decimal("0.02"),
    "Regular": Decimal("0.01"),
    "Premium": Decimal("0.03"),
}

TWO_PLACES = Decimal("0.01")


async def create_orders(store_id, cart_id, db, request, background_task):
    user_id = unique_id(request)
    if not user_id:
        logger.warning("Unauthorized attempt to create order")
        raise HTTPException(
            status_code=401, detail="you must be a registered user to make orders"
        )
    try:
        stmt = (
            select(Cart)
            .options(
                joinedload(Cart.store),
                selectinload(Cart.cartitems)
                .selectinload(CartItem.variant)
                .selectinload(ProductVariant.product),
            )
            .where(
                Cart.id == cart_id,
                Cart.check_out.is_(False),
                Cart.user_id == user_id,
                Cart.store_id == store_id,
            )
            .with_for_update(of=Cart)
        )
        result = await db.execute(stmt)
        cart = result.scalar_one_or_none()
        logger.info(f"Fetched cart items for cart_id: {cart_id}")
        if not cart:
            logger.warning(
                "user: %s, tried making an order with a non existent cart", user_id
            )
            raise HTTPException(status_code=404, detail="cart not found")
        if not cart.cartitems:
            raise HTTPException(status_code=404, detail="no cart items found")
        logger.info("Creating order for user_id: %s", user_id)
        membership = (
            await db.execute(
                select(Membership).where(
                    Membership.user_id == user_id,
                    Membership.store_id == store_id,
                    Membership.is_active.is_(True),
                )
            )
        ).scalar_one_or_none()
        membership_id = membership.id if membership else None
        order = Order(
            user_id=user_id,
            store_id=store_id,
            member_id=membership_id,
            created_at=datetime.now(timezone.utc),
        )
        db.add(order)
        await db.flush()
        if not order.id:
            logger.warning("No order created")
            raise HTTPException(status_code=404, detail="no order created")
        variant_ids = sorted([items.variant_id for items in cart.cartitems])
        inventory = (
            (
                await db.execute(
                    select(Inventory)
                    .where(
                        Inventory.variant_id.in_(variant_ids),
                        Inventory.is_deleted.is_(False),
                    )
                    .with_for_update(),
                )
            )
            .scalars()
            .all()
        )
        cart_variant_ids = {i.variant_id for i in cart.cartitems}
        inventory_variant_ids = {inv.variant_id for inv in inventory}
        if cart_variant_ids != inventory_variant_ids:
            logger.warning(
                "inventory mismatch at create_order_items endpoint",
            )
            raise HTTPException(404, "inventory mismatch")
        inventory_map = {inv.variant_id: inv for inv in inventory}
        items = [
            i
            for i in cart.cartitems
            if i.variant.is_deleted
            or i.quantity > inventory_map[i.variant_id].stock_quantity
            or i.variant.product.product_availability != "available"
        ]
        if items:
            raise HTTPException(
                status_code=400,
                detail="there is an update on your cart, please update cart before check out",
            )
        new_orderitems = []
        total_quantity = 0
        subtotal = Decimal("0.00")
        product_to_check = set()
        for cartitem in cart.cartitems:
            variant = cartitem.variant
            price = (cartitem.variant.price * Decimal(str(cartitem.quantity))).quantize(
                TWO_PLACES
            )
            new_orderitems.append(
                OrderItem(
                    order_id=order.id,
                    variant_id=cartitem.variant_id,
                    quantity=cartitem.quantity,
                    price=price,
                )
            )
            target_inventory = inventory_map[cartitem.variant_id]
            target_inventory.stock_quantity = max(
                target_inventory.stock_quantity - cartitem.quantity, 0
            )
            total_quantity += cartitem.quantity
            subtotal += price
            if target_inventory.stock_quantity == 0:
                await db.flush()
                product_to_check.add(variant.product_id)
        logger.info(f"product to check: {product_to_check}")
        if product_to_check:
            remaining_stock = (
                (
                    await db.execute(
                        select(ProductVariant.product_id)
                        .join(
                            Inventory,
                            ProductVariant.id == Inventory.variant_id,
                        )
                        .where(
                            ProductVariant.product_id.in_(product_to_check),
                            ProductVariant.is_deleted.is_(False),
                            Inventory.is_deleted.is_(False),
                            Inventory.stock_quantity > 0,
                        )
                    )
                )
                .scalars()
                .all()
            )
            out_of_stock_products = product_to_check - set(remaining_stock)
            logger.info(f"out of stock; {out_of_stock_products}")
            if out_of_stock_products:
                (
                    await db.execute(
                        update(Product)
                        .where(Product.id.in_(out_of_stock_products))
                        .values(product_availability="out_of_stock")
                    )
                )
        order.total_quantity = total_quantity
        order.subtotal = subtotal.quantize(TWO_PLACES)
        order.discount_amount = Decimal("0.00")
        has_premium = membership and membership.membership_type == "Premium"
        if membership:
            order.discount_amount = (
                subtotal * Decimal(str(DISCOUNT_MAP[membership.membership_type]))
            ).quantize(TWO_PLACES)
        order.shipping_fee = Decimal("0.00") if has_premium else cart.store.shipping_fee
        tax_amount = (
            (subtotal * Decimal(str(cart.store.tax_rate))) / Decimal("100")
        ).quantize(TWO_PLACES)
        order.tax_rate = cart.store.tax_rate
        order.tax_amount = tax_amount
        order.total_amount = (
            (subtotal + order.shipping_fee + tax_amount) - order.discount_amount
        ).quantize(TWO_PLACES)
        db.add_all(new_orderitems)
        update_result = (
            await db.execute(
                update(Cart)
                .where(
                    Cart.id == cart_id,
                    Cart.check_out.is_(False),
                    Cart.user_id == user_id,
                )
                .values(check_out=True)
                .returning(Cart.id)
            )
        ).scalar()
        if update_result is None:
            raise HTTPException(status_code=409, detail="cart already checked out")
        order_id = order.id
        await db.commit()
    except HTTPException:
        await db.rollback()
        raise
    except IntegrityError as e:
        await db.rollback()
        logger.error(f"Database integrity error while creating order items {e}")
        raise HTTPException(status_code=400, detail="database error")
    except Exception:
        await db.rollback()
        logger.exception("error while creating order items")
        raise HTTPException(status_code=500, detail="internal server error")
    background_task.add_task(cart_invalidation, user_id)
    background_task.add_task(order_global_invalidation, store_id)
    logger.info("order items created successfully for order_id: %s", order_id)
    return StandardResponse(
        status="success",
        message="order item successfully created",
        data=f"you have one hour to check out the order, order_id: '{order_id}'",
    )


async def view_orders(store_id, page, limit, db, request):
    user_id = unique_id(request)
    if not user_id:
        logger.error("Unauthorized attempt to view orders")
        raise HTTPException(status_code=401, detail="not a registered buyer")
    offset = (page - 1) * limit
    version = await cache_version(f"store_order_key:{store_id}")
    order_key = f"orders:v{version}:{user_id}:{store_id}:{page}:{limit}"
    cache_key = await cache(order_key)
    if cache_key:
        logger.info(
            "cache hit at view_orders function for user: %s, in store: %s",
            user_id,
            store_id,
        )
        return StandardResponse(**cache_key)
    total = (
        await db.execute(
            select(func.count(Order.id)).where(
                Order.user_id == user_id,
                Order.store_id == store_id,
                Order.order_delete.is_(False),
            )
        )
    ).scalar() or 0
    if total == 0:
        store_exists = (
            await db.execute(select(exists().where(Store.id == store_id)))
        ).scalar()
        if not store_exists:
            logger.warning(
                "user: %s, tried querying orders from a store that does not exist",
                user_id,
            )
            raise HTTPException(status_code=404, detail="store not found")
        logger.info(
            "search for orders by user %s in store %s returned null", user_id, store_id
        )
        empty_response = PaginatedMetadata[OrderResponse](
            items=[], pagination=PaginatedResponse(page=page, limit=limit, total=0)
        )
        response = StandardResponse(
            status="success", message="orders", data=empty_response
        )
        await cached(order_key, response, 3600)
        return response
    logger.info("total orders found: '%s' for user: %s", total, user_id)
    stmt = (
        select(Order)
        .options(
            selectinload(Order.orderitems)
            .selectinload(OrderItem.variant)
            .selectinload(ProductVariant.inventory),
            selectinload(Order.membership),
            selectinload(Order.user),
        )
        .where(
            Order.user_id == user_id,
            Order.store_id == store_id,
            Order.order_delete.is_(False),
        )
    )
    order = (await db.execute(stmt.offset(offset).limit(limit))).scalars().all()
    logger.info("preparing paginated response for orders of user: %s", user_id)
    data = PaginatedMetadata[OrderResponse](
        items=[OrderResponse.model_validate(od) for od in order],
        pagination=PaginatedResponse(page=page, limit=limit, total=total),
    )
    logger.info("Orders retrieved successfully for user_id: %s", user_id)
    full_response = StandardResponse(status="success", message="orders", data=data)
    await cached(order_key, full_response, ttl=3600)
    return full_response


async def view_store_orders(store_id, limit, status, cursor_id, db, request):
    user_id = await store_auth(store_id=store_id, db=db, request=request)
    version = await cache_version(f"store_order_key:{store_id}")
    status_str = status.value if hasattr(status, "value") else (status or "all")
    order_key = (
        f"store_orders:v{version}:{user_id}:{store_id}:{status_str}:{limit}:{cursor_id}"
    )
    cache_key = await cache(order_key)
    if cache_key:
        logger.info(
            "cache hit at view_store_orders function for store: %s, status: %s, by user: %s",
            store_id,
            status_str,
            user_id,
        )
        return StandardResponse(**cache_key)
    stmt = (
        select(Order)
        .options(
            selectinload(Order.orderitems)
            .selectinload(OrderItem.variant)
            .selectinload(ProductVariant.inventory),
            selectinload(Order.membership),
            selectinload(Order.user),
        )
        .where(
            Order.store_id == store_id,
            Order.order_delete.is_(False),
        )
        .order_by(Order.id.asc())
    )
    if status_str != "all":
        stmt = stmt.where(Order.status == status_str)
    if cursor_id is not None:
        stmt = stmt.where(Order.id > cursor_id)
    orders = (await db.execute(stmt.limit(limit + 1))).scalars().all()
    if not orders:
        logger.warning("search for %s orders returned no result", status_str)
    has_more = len(orders) > limit
    if has_more:
        orders = orders[:limit]
    next_cursor = orders[-1].id if orders else None
    logger.info("preparing paginated response for orders of user: %s", user_id)
    data = PaginatedMetadata[OrderResponse](
        items=[OrderResponse.model_validate(od) for od in orders],
        cursor_pagination=CursorPaginatedResponse(
            next_cursor=next_cursor, limit=limit, has_more=has_more
        ),
    )
    logger.info("%s orders retrieved successfully for user_id: %s", status_str, user_id)
    full_response = StandardResponse(
        status="success", message=f"{status_str} orders retrieved", data=data
    )
    await cached(order_key, full_response, ttl=300)
    return full_response


async def view_store_order(store_id, order_id, page, limit, db, request):
    user_id = await store_auth(store_id=store_id, db=db, request=request)
    offset = (page - 1) * limit
    version = await cache_version(f"store_order_key:{store_id}")
    logger.info("version %s", version)
    order_key = f"orders:v{version}:{user_id}:{store_id}:{order_id}:{page}:{limit}"
    cache_key = await cache(order_key)
    if cache_key:
        logger.info(
            "cache hit at view_store_order function for store: %s, order_id: %s by user: %s",
            store_id,
            order_id,
            user_id,
        )
        return StandardResponse(**cache_key)
    stmt = (
        select(Order)
        .options(
            selectinload(Order.orderitems)
            .selectinload(OrderItem.variant)
            .selectinload(ProductVariant.inventory),
            selectinload(Order.payment),
            selectinload(Order.user),
            selectinload(Order.membership),
        )
        .where(
            Order.store_id == store_id,
            Order.id == order_id,
            Order.order_delete.is_(False),
        )
    )
    order = (await db.execute(stmt)).scalar_one_or_none()
    if not order:
        logger.error("Order with order_id: '%s' not found", order_id)
        raise HTTPException(
            status_code=404, detail=f"order with the order id: {order_id} not found"
        )
    order_data = OrderResponse.model_validate(order)
    total = len(order.orderitems)
    items = order.orderitems[offset : offset + limit]
    logger.info("Total order items found: %s for order_id: %s", total, order_id)
    logger.info(
        "Preparing paginated response for order items of order_id: %s", order_id
    )
    data = PaginatedMetadata[OrderItemRes](
        items=[OrderItemRes.model_validate(item) for item in items],
        pagination=PaginatedResponse(page=page, limit=limit, total=total),
    )
    response = {"order": order_data, "ordered_items": data}
    full_response = StandardResponse(
        status="success", message="order retrieved successfully", data=response
    )
    await cached(order_key, full_response, ttl=3600)
    logger.info("Order details retrieved successfully for order_id: %s", order_id)
    return full_response


async def view_order(store_id, order_id, page, limit, db, request):
    user_id = unique_id(request)
    if not user_id:
        logger.error("Unauthorized attempt to view order")
        raise HTTPException(status_code=401, detail="not a registered buyer")
    offset = (page - 1) * limit
    version = await cache_version(f"store_order_key:{store_id}")
    order_key = f"orders:v{version}:{user_id}:{store_id}:{order_id}:{page}:{limit}"
    cache_key = await cache(order_key)
    if cache_key:
        logger.info(
            "cache hit at view_order function for store: %s, by user: %s",
            store_id,
            user_id,
        )
        return StandardResponse(**cache_key)
    stmt = (
        select(Order)
        .options(
            selectinload(Order.orderitems)
            .selectinload(OrderItem.variant)
            .selectinload(ProductVariant.inventory),
            selectinload(Order.payment),
            selectinload(Order.user),
            selectinload(Order.membership),
        )
        .where(
            Order.user_id == user_id,
            Order.store_id == store_id,
            Order.id == order_id,
            Order.order_delete.is_(False),
        )
    )
    order = (await db.execute(stmt)).scalar_one_or_none()
    if not order:
        logger.error("Order with order_id: '%s' not found", order_id)
        raise HTTPException(
            status_code=404, detail=f"order with the order id: {order_id} not found"
        )
    order_data = OrderResponse.model_validate(order)
    total = len(order.orderitems)
    items = order.orderitems[offset : offset + limit]
    logger.info("Total order items found: %s for order_id: %s", total, order_id)
    logger.info(
        "Preparing paginated response for order items of order_id: %s", order_id
    )
    data = PaginatedMetadata[OrderItemRes](
        items=[OrderItemRes.model_validate(item) for item in items],
        pagination=PaginatedResponse(page=page, limit=limit, total=total),
    )
    response = {"order": order_data, "ordered_items": data}
    full_response = StandardResponse(
        status="success", message="order retrieved successfully", data=response
    )
    await cached(order_key, full_response, ttl=3600)
    logger.info("Order details retrieved successfully for order_id: %s", order_id)
    return full_response


async def reactivate_order(store_id, order_id, db, request, background_task):
    user_id = unique_id(request)
    if not user_id:
        logger.warning("unauthorized attempt at checkout endpoint")
        raise HTTPException(status_code=401, detail="unauthorized access")
    try:
        stmt = (
            select(Order)
            .options(
                joinedload(Order.store),
                selectinload(Order.orderitems)
                .selectinload(OrderItem.variant)
                .selectinload(ProductVariant.product),
            )
            .where(
                Order.user_id == user_id,
                Order.store_id == store_id,
                Order.id == order_id,
                Order.order_delete.is_(False),
                Order.status == OrderStatus.cancelled,
            )
            .with_for_update(of=Order)
        )
        res = await db.execute(stmt)
        order = res.scalar_one_or_none()
        if not order:
            logger.warning(
                "user: '%s', tried to re-order a non existent order", user_id
            )
            raise HTTPException(status_code=404, detail="order not found")
        if not order.orderitems:
            logger.warning("order: '%s' was created without orderitems", order_id)
            raise HTTPException(status_code=400, detail="order contains no items")
        variant_ids = sorted([item.variant_id for item in order.orderitems])
        inventory = (
            (
                await db.execute(
                    select(Inventory)
                    .where(
                        Inventory.variant_id.in_(variant_ids),
                        Inventory.is_deleted.is_(False),
                    )
                    .with_for_update(),
                )
            )
            .scalars()
            .all()
        )
        order_variant_ids = {item.variant_id for item in order.orderitems}
        inventory_variant_ids = {inv.variant_id for inv in inventory}
        if order_variant_ids != inventory_variant_ids:
            logger.warning(
                "user: '%s', reactivation failed. Some product variants are no longer available in catalog",
                user_id,
            )
            raise HTTPException(
                status_code=404,
                detail="Cannot reactivate order. Some items in this order are no longer available.",
            )
        membership_stmt = select(Membership).where(
            Membership.store_id == store_id,
            Membership.user_id == user_id,
            Membership.is_active,
        )
        membership_result = await db.execute(membership_stmt)
        membership = membership_result.scalar_one_or_none()
        has_premium = membership and membership.membership_type == "Premium"
        inventory_map = {inv.variant_id: inv for inv in inventory}
        failed_item = None
        for item in order.orderitems:
            if (
                inventory_map[item.variant_id].stock_quantity < item.quantity
                or item.variant.is_deleted
                or item.variant.product.product_availability != "available"
            ):
                failed_item = item
                break
        if failed_item:
            variant = failed_item.variant
            available_inventory = inventory_map[failed_item.variant_id].stock_quantity
            reason = None
            if available_inventory < failed_item.quantity:
                reason = "insufficient stock"
            elif variant.is_deleted:
                reason = "product deleted"
            elif variant.product.product_availability != "available":
                reason = "product unavailable"
            logger.warning("user '%s' reactivation failed, reason: %s", user_id, reason)
            raise HTTPException(status_code=400, detail=reason)
        new_subtotal = Decimal("0.00")
        order.status = OrderStatus.pending
        tax_rate = order.store.tax_rate
        shipping_fee = Decimal("0.00") if has_premium else order.store.shipping_fee
        order.re_order_time = datetime.now(timezone.utc)
        product_to_check = set()
        for orderitems in order.orderitems:
            product_variant = orderitems.variant
            current_item_price = product_variant.price * Decimal(
                str(orderitems.quantity)
            )
            orderitems.price = current_item_price
            new_subtotal += current_item_price
            target_inventory = inventory_map[orderitems.variant_id]
            target_inventory.stock_quantity -= orderitems.quantity
            if target_inventory.stock_quantity == 0:
                product_to_check.add(product_variant.product_id)
                await db.flush()
        if product_to_check:
            remaining_stock = (
                (
                    await db.execute(
                        select(ProductVariant.product_id)
                        .join(
                            Inventory,
                            ProductVariant.id == Inventory.variant_id,
                        )
                        .where(
                            ProductVariant.product_id.in_(product_to_check),
                            ProductVariant.is_deleted.is_(False),
                            Inventory.is_deleted.is_(False),
                            Inventory.stock_quantity > 0,
                        )
                    )
                )
                .scalars()
                .all()
            )
            out_of_stock_products = product_to_check - set(remaining_stock)
            if out_of_stock_products:
                (
                    await db.execute(
                        update(Product)
                        .where(Product.id.in_(out_of_stock_products))
                        .values(product_availability="out_of_stock")
                    )
                )
        tax_amount = (new_subtotal * Decimal(str(tax_rate)) / Decimal("100")).quantize(
            TWO_PLACES
        )
        order.discount_amount = Decimal("0.00")
        if membership:
            order.discount_amount = (
                new_subtotal * Decimal(str(DISCOUNT_MAP[membership.membership_type]))
            ).quantize(TWO_PLACES)
        order.tax_rate = tax_rate
        order.tax_amount = tax_amount
        order.shipping_fee = shipping_fee
        order.subtotal = new_subtotal.quantize(TWO_PLACES)
        order.total_amount = (
            (new_subtotal + tax_amount + shipping_fee) - order.discount_amount
        ).quantize(TWO_PLACES)
        await db.commit()
    except HTTPException:
        await db.rollback()
        raise
    except IntegrityError:
        await db.rollback()
        logger.error("database integrity error at re-order endpoint")
        raise HTTPException(status_code=400, detail="database error")
    except Exception:
        await db.rollback()
        logger.exception("error at re-order endpoint")
        raise HTTPException(status_code=500, detail="internal server error")
    background_task.add_task(order_global_invalidation, store_id)
    logger.info("Order: '%s' successfully re-ordered", order_id)
    return StandardResponse(
        status="success",
        message="re-order successful",
        data="you have 30 minutes to check out this order, if this order is not checked out after 30 minutes, it will be automatically deleted",
    )


async def proceed_to_payment_portal(store_id, order_id, db, request):
    user_id = unique_id(request)
    if not user_id:
        logger.warning("Unauthorized access attempt for order_id=%s", order_id)
        raise HTTPException(status_code=401, detail="unauthorized access")
    try:
        checkout = (
            await db.execute(
                select(Order)
                .options(
                    selectinload(Order.address),
                    selectinload(Order.orderitems)
                    .selectinload(OrderItem.variant)
                    .options(
                        selectinload(ProductVariant.inventory),
                        selectinload(ProductVariant.product),
                    ),
                )
                .where(
                    Order.user_id == user_id,
                    Order.order_delete.is_(False),
                    Order.id == order_id,
                    Order.store_id == store_id,
                    Order.status == OrderStatus.pending,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if not checkout:
            logger.warning(
                "user: %s attempted payment for non-existent or invalid order %s",
                user_id,
                order_id,
            )
            raise HTTPException(
                status_code=404,
                detail="order not found, if you think this is a mistake try again shortly",
            )
        now = datetime.now(timezone.utc)
        retry_limit = now - timedelta(minutes=30)
        time_limit = now - timedelta(hours=1)
        is_expired = False
        if checkout.re_order_time and checkout.re_order_time <= retry_limit:
            checkout.order_delete = True
            is_expired = True
        elif not checkout.re_order_time and checkout.created_at <= time_limit:
            is_expired = True
        if is_expired:
            try:
                checkout.status = OrderStatus.cancelled
                if checkout.orderitems:
                    restore_inventory(checkout)
                await db.commit()
            except IntegrityError:
                await db.rollback()
                logger.error(
                    "Database integrity error while  updating checked out order"
                )
                raise HTTPException(status_code=400, detail="database integrity error")
            except Exception:
                await db.rollback()
                logger.exception("error while updating checked out order")
                raise HTTPException(status_code=500, detail="internal server error")
            raise HTTPException(
                status_code=409,
                detail="Order session expired. Please re-initiate order",
            )
        checkout_addr = (
            checkout.address
            if checkout.address and not checkout.address.is_deleted
            else None
        )
        if not checkout_addr:
            logger.warning(
                "user: %s attempted payment for order %s without delivery address",
                user_id,
                order_id,
            )
            raise HTTPException(
                status_code=400,
                detail="Delivery address required before proceeding to payment",
            )
        buffer_time = timedelta(minutes=5)
        if checkout.re_order_time:
            checkout.re_order_time += buffer_time
        await db.commit()
    except HTTPException:
        await db.rollback()
        raise
    except Exception:
        await db.rollback()
        logger.exception(
            "Failed to persist checkout window update for order: %s", order_id
        )
        raise HTTPException(status_code=500, detail="Database transaction failure")
    logger.info(
        "Order %s validated successfully. Proceeding to payment portal.", order_id
    )


async def toggle_status(store_id, order_id, request, background_task, status, db):
    user_id = await store_auth(store_id=store_id, request=request, db=db)
    try:
        new_status = OrderStatus(status)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid status '{status}'. Valid options: {[e.value for e in OrderStatus]}",
        )
    try:
        order_stmt = (
            select(Order)
            .options(
                selectinload(Order.payment).selectinload(Payment.refunds),
                selectinload(Order.orderitems)
                .selectinload(OrderItem.variant)
                .options(
                    selectinload(ProductVariant.inventory),
                    selectinload(ProductVariant.product),
                ),
            )
            .where(
                Order.id == order_id,
                Order.store_id == store_id,
                Order.status.in_(
                    [OrderStatus.processing, OrderStatus.shipped, OrderStatus.pending]
                ),
                Order.order_delete.is_(False),
            )
            .with_for_update(of=Order)
        )
        order = (await db.execute(order_stmt)).scalar_one_or_none()
        if not order:
            logger.warning(
                "Store: %s attempted to toggle status for non-existent or invalid order %s",
                store_id,
                order_id,
            )
            raise HTTPException(status_code=404, detail="order not found")
        if order.payment and status in [OrderStatus.pending, OrderStatus.cancelled]:
            refunds = order.payment.refunds or []
            total_refunds = sum(
                (Decimal(str(r.refund_amount)) for r in refunds), Decimal("0")
            )
            if Decimal(str(order.payment.total_amount)) != total_refunds:
                logger.warning(
                    "User: %s attempted to regress status for order %s with successful payment",
                    user_id,
                    order_id,
                )
                raise HTTPException(
                    status_code=400,
                    detail="you need to fully refund customer before you cancel or revert order to pending",
                )
        if order.status == OrderStatus.pending:
            if (
                not order.payment
                or order.payment.payment_status != PaymentStatus.SUCCESS.value
            ):
                if new_status in [
                    OrderStatus.shipped,
                    OrderStatus.processing,
                    OrderStatus.delivered,
                ]:
                    logger.warning(
                        "User: %s attempted to progress status for order %s without successful payment",
                        user_id,
                        order_id,
                    )
                    raise HTTPException(
                        status_code=400,
                        detail="you cannot progress order status to shipped, processing or delivered when the order is not paid for",
                    )
        order.status = new_status
        if new_status == OrderStatus.cancelled:
            restore_inventory(order)
        await db.commit()
    except HTTPException:
        await db.rollback()
        raise
    except IntegrityError:
        await db.rollback()
        logger.error("Database integrity error while updating order status")
        raise HTTPException(status_code=400, detail="database integrity error")
    except Exception:
        await db.rollback()
        logger.exception("Error while updating order status")
        raise HTTPException(status_code=500, detail="internal server error")
    logger.info(
        "Order %s status updated to %s successfully by store %s",
        order_id,
        status.value,
        store_id,
    )
    background_task.add_task(order_global_invalidation, store_id)
    return StandardResponse(
        status="success",
        message=f"order status updated to {status.value}",
        data=None,
    )


async def cancel_order(store_id, order_id, db, request, background_task):
    user_id = unique_id(request)
    if not user_id:
        logger.error("Unauthorized attempt to cancel order")
        raise HTTPException(status_code=401, detail="not authorized")
    try:
        stmt = (
            select(Order)
            .options(
                selectinload(Order.payment),
                selectinload(Order.orderitems)
                .selectinload(OrderItem.variant)
                .options(
                    selectinload(ProductVariant.inventory),
                    selectinload(ProductVariant.product),
                ),
            )
            .where(
                Order.user_id == user_id,
                Order.store_id == store_id,
                Order.id == order_id,
                Order.order_delete.is_(False),
                Order.status == OrderStatus.pending,
            )
            .with_for_update(of=Order)
        )
        logger.info("fetching order to cancel for order_id: %s", order_id)
        result = (await db.execute(stmt)).scalar_one_or_none()
        if not result:
            logger.error(
                "Order with order_id: '%s' not found for cancellation", order_id
            )
            raise HTTPException(status_code=404, detail="order not found")
        payment_status = result.payment.payment_status if result.payment else "pending"
        if payment_status == "pending":
            result.status = OrderStatus.cancelled
            if result.orderitems:
                restore_inventory(result)
            logger.info("Order with order_id: '%s' cancelled successfully", order_id)
        else:
            logger.error(
                "Order with order_id: '%s' cannot be cancelled, payment triggered",
                order_id,
            )
            raise HTTPException(
                status_code=400, detail="payment is triggered, cannot cancel order"
            )
        await db.commit()
    except HTTPException:
        await db.rollback()
        raise
    except IntegrityError:
        await db.rollback()
        logger.error("Database integrity error while cancelling order")
        raise HTTPException(status_code=400, detail="database error")
    except Exception:
        await db.rollback()
        logger.exception("error while cancelling order")
        raise HTTPException(status_code=500, detail="internal server error")
    background_task.add_task(order_global_invalidation, store_id)
    logger.info("Order cancellation process completed for order_id: %s", order_id)
    return StandardResponse(status="success", message="order cancelled", data=None)


async def delete_order(store_id, order_id, db, request, background_task):
    user_id = unique_id(request)
    if not user_id:
        logger.error("Unauthorized attempt to delete order")
        raise HTTPException(status_code=401, detail="not authorized")
    try:
        logger.info("Fetching order to delete for order_id: %s", order_id)
        stmt = (
            select(Order)
            .where(
                Order.user_id == user_id,
                Order.order_delete.is_(False),
                Order.store_id == store_id,
                Order.id == order_id,
            )
            .with_for_update()
        )
        result = (await db.execute(stmt)).scalar_one_or_none()
        if not result:
            logger.error("Order with order_id: '%s' not found for deletion", order_id)
            raise HTTPException(status_code=404, detail="order not found")
        if result.status not in [
            OrderStatus.cancelled,
            OrderStatus.delivered,
            OrderStatus.shipped,
        ]:
            raise HTTPException(
                status_code=400,
                detail="Cannot delete an active order. Please cancel it first.",
            )
        result.order_delete = True
        await db.commit()
    except HTTPException:
        await db.rollback()
        raise
    except IntegrityError:
        await db.rollback()
        logger.error("Database integrity error while deleting order")
        raise HTTPException(status_code=500, detail="database error")
    except Exception:
        await db.rollback()
        logger.exception("error while deleting order")
        raise HTTPException(status_code=500, detail="internal server error")
    background_task.add_task(order_global_invalidation, store_id)
    logger.info("Order deletion process completed for order_id: %s", order_id)
    return StandardResponse(status="success", message="order deleted", data=None)
