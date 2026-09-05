from app.api.v1.schemas import (
    CartResponse,
    PaginatedMetadata,
    PaginatedResponse,
    StandardResponse,
    CartItemReponse,
)
from app.models import Cart, CartItem, Product, Inventory, Store, ProductVariant
from fastapi import HTTPException
from app.logs.logger import get_logger
from sqlalchemy import select, func, delete, exists
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import IntegrityError
from app.utils.helper import unique_id
from app.utils.redis import cache, cached, cart_invalidation, cache_version

logger = get_logger("cart")


async def add_item_to_cart(
    store_id, request, variant_id, quantity, db, background_task
):
    user_id = unique_id(request)
    if not user_id:
        logger.warning("unauthorized attempt at create_cart function")
        raise HTTPException(
            status_code=401, detail="you must be a registered user to shop"
        )
    logger.info(f"Creating cart for user {user_id}")
    subq = select(
        select(exists().where(Store.id == store_id, Store.is_deleted.is_(False)))
        .scalar_subquery()
        .label("store_check"),
        select(func.count(Cart.id))
        .where(Cart.user_id == user_id, Cart.check_out.is_(False))
        .scalar_subquery()
        .label("cart_check"),
    )
    result = (await db.execute(subq)).mappings().first()
    if not result["store_check"]:
        logger.warning("user: %s, tried creating cart for a non existent store")
        raise HTTPException(status_code=404, detail="store not found")
    if not result["cart_check"] >= 1:
        cart = Cart(user_id=user_id, store_id=store_id)
        try:
            db.add(cart)
            await db.flush()
            await cart_invalidation(user_id=user_id)
        except IntegrityError as e:
            await db.rollback()
            logger.error("Database integrity error while creating cart %s", e)
            raise HTTPException(status_code=400, detail="database error")
        except Exception:
            await db.rollback()
            logger.exception("error while creating cart")
            raise HTTPException(status_code=500, detail="internal server error")
        logger.info(f"Cart created successfully for user {user_id}")
        try:
            cart_stmt = (
                select(Cart)
                .options(selectinload(Cart.cartitems))
                .where(Cart.user_id == user_id, Cart.check_out.is_(False))
                .with_for_update()
            )
            result = await db.execute(cart_stmt)
            cart = result.scalar_one_or_none()
            if not cart:
                logger.warning("user: '%s' tried adding to cart that does not exist")
                raise HTTPException(
                    status_code=400,
                    detail="pick a cart, if you already have a cart, verify the product availability before proceeding",
                )
        except HTTPException:
            await db.rollback()
            raise
    else:
        try:
            cart_stmt = (
                select(Cart)
                .options(selectinload(Cart.cartitems))
                .where(Cart.user_id == user_id, Cart.check_out.is_(False))
                .with_for_update()
            )
            result = await db.execute(cart_stmt)
            cart = result.scalar_one_or_none()
            if not cart:
                logger.warning("user: '%s' tried adding to cart that does not exist")
                raise HTTPException(
                    status_code=400,
                    detail="pick a cart, if you already have a cart, verify the product availability before proceeding",
                )
        except HTTPException:
            await db.rollback()
            raise
    logger.info(
        "user: '%s' is attempting to add product variant: '%s' to cart: %s",
        user_id,
        variant_id,
        cart.id,
    )
    available = (
        await db.execute(
            select(
                exists(
                    select(1)
                    .select_from(ProductVariant)
                    .join(Product, ProductVariant.product_id == Product.id)
                    .join(Store, ProductVariant.store_id == Store.id)
                    .join(Inventory, Inventory.variant_id == ProductVariant.id)
                    .where(
                        Store.id == store_id,
                        ProductVariant.id == variant_id,
                        Product.product_availability == "available",
                        ProductVariant.is_deleted.is_(False),
                        Product.is_deleted.is_(False),
                        Store.is_deleted.is_(False),
                        Inventory.stock_quantity >= quantity,
                    )
                )
            )
        )
    ).scalar()
    if not available:
        logger.warning(
            "User: '%s' attempted to add product variant: '%s' to cart: '%s' from store: '%s', but the product is either out of stock, the requested quantity is not available, or the store does not exist",
            user_id,
            variant_id,
            cart.id,
            store_id,
        )
        raise HTTPException(
            status_code=400,
            detail="required quantity not available or product out of stock or store not found",
        )
    cartitem = next(
        (item for item in cart.cartitems if item.variant_id == variant_id), None
    )
    if not cartitem and len(cart.cartitems) >= 30:
        raise HTTPException(status_code=403, detail="cart full")
    if cartitem:
        cartitem.quantity += quantity
    else:
        items = CartItem(
            cart_id=cart.id,
            variant_id=variant_id,
            quantity=quantity,
        )
        db.add(items)
    cart.total_quantity += quantity
    logger.info(
        "adding product variant: '%s' to cart: '%s' for user: %s",
        variant_id,
        cart.id,
        user_id,
    )
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        logger.error("Database integrity error while adding product variant to cart")
        raise HTTPException(status_code=400, detail="database error")
    except Exception:
        await db.rollback()
        logger.exception("error while adding product variant to cart")
        raise HTTPException(status_code=500, detail="internal server error")
    logger.info(
        "product variant: %s added to cart: %s for user: %s",
        variant_id,
        cart.id,
        user_id,
    )
    background_task.add_task(cart_invalidation, user_id)
    return StandardResponse(
        status="success", message="product added to cart", data=None
    )


async def retrieve_cart(store_id, request, page, limit, db):
    user_id = unique_id(request)
    if not user_id:
        logger.warning("unauthorized attempt at the retrieve_cart function")
        raise HTTPException(status_code=401, detail="not a registered buyer")
    offset = (page - 1) * limit
    version = await cache_version(f"store_cart_key:{store_id}")
    cart_keys = f"carts:v{version}:{user_id}:{store_id}:{page}:{limit}"
    cached_data = await cache(cart_keys)
    if cached_data:
        logger.info("Cache hit for cart, for user: %s", user_id)
        return StandardResponse(**cached_data)
    stmt = (
        select(Cart)
        .options(
            selectinload(Cart.cartitems)
            .selectinload(CartItem.variant)
            .selectinload(ProductVariant.product)
        )
        .where(
            Cart.user_id == user_id,
            Cart.store_id == store_id,
            Cart.check_out.is_(False),
        )
    )
    cart = (await db.execute(stmt)).scalar_one_or_none()
    if not cart:
        logger.error("user %s, tried retrieving a non-existent cart", user_id)
        raise HTTPException(status_code=404, detail="no cart found")
    logger.info(f"Cart found for user {user_id}, retrieving items")
    cart_model = CartResponse.model_validate(cart)
    total = len(cart.cartitems)
    logger.info("total number of cart items found in cart %s", total)
    items = cart.cartitems[offset : offset + limit]
    logger.info("%s items found in cart for user: %s", total, user_id)
    cartitem_model = PaginatedMetadata[CartItemReponse](
        items=[CartItemReponse.model_validate(cartitem) for cartitem in items],
        pagination=PaginatedResponse(page=page, limit=limit, total=total),
    )
    data = {"cart": cart_model, "cart_item": cartitem_model}
    full_data = StandardResponse(status="success", message="cart", data=data)
    await cached(cart_keys, full_data, ttl=3600)
    logger.info("Cart data cached for user %s", user_id)
    return full_data


async def edit_quantity(store_id, request, cart_id, cartitem_id, new_quantity, db):
    user_id = unique_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="register and continue")
    logger.info(
        f"Attempting to edit quantity of cart item {cartitem_id} in cart {cart_id}"
    )
    try:
        stmt = (
            select(Cart, CartItem)
            .join(CartItem, Cart.id == CartItem.cart_id)
            .where(
                Cart.id == cart_id,
                Cart.store_id == store_id,
                Cart.user_id == user_id,
                CartItem.id == cartitem_id,
            )
            .with_for_update()
        )
        row = (await db.execute(stmt)).fetchone()
        if not row:
            logger.warning(
                "user %s, queried a non existent cart or cart item in edit_quantity function",
                user_id,
            )
            raise HTTPException(status_code=404, detail="cart or cart item not found")
        cart, target_item = row
        if target_item.quantity == new_quantity:
            return StandardResponse(
                status="success", message="no quantity change", data=None
            )
        old_quantity = target_item.quantity
        difference = new_quantity - old_quantity
        target_item.quantity = new_quantity
        logger.info(
            f"Cart item {cartitem_id} found in cart {cart_id} for user {user_id}, updating quantity from {old_quantity} to {new_quantity}"
        )
        cart.total_quantity += difference
        await db.commit()
        await cart_invalidation(user_id=user_id)
    except HTTPException:
        await db.rollback()
        raise
    except IntegrityError:
        await db.rollback()
        logger.exception("database error at edit_quantity function")
        raise HTTPException(status_code=400, detail="database error")
    except Exception:
        await db.rollback()
        logger.exception("Failed to commit")
        raise HTTPException(status_code=500, detail="internal server error")
    logger.info(
        f"Cart item {cartitem_id} quantity updated successfully in cart {cart_id} for user {user_id}"
    )
    return StandardResponse(
        status="success", message="cart item quantity updated", data=None
    )


async def update_cart(cart_id, store_id, request, db):
    user_id = unique_id(request)
    if not user_id:
        logger.warning("unauthorized attempt to access update_cart endpoint")
        raise HTTPException(status_code=401, detail="not authorized")
    try:
        stmt = (
            select(Cart)
            .options(
                selectinload(Cart.cartitems)
                .selectinload(CartItem.variant)
                .selectinload(ProductVariant.inventory)
            )
            .where(
                Cart.user_id == user_id, Cart.store_id == store_id, Cart.id == cart_id
            )
        ).with_for_update()
        result = (await db.execute(stmt)).scalar_one_or_none()
        if not result:
            logger.error("user %s, tried updating a non-existent cart", user_id)
            raise HTTPException(status_code=404, detail="cart not found")
        remove_items = {}
        for item in result.cartitems:
            if item.variant.is_deleted:
                remove_items[item.id] = item
            if item.variant.inventory.stock_quantity < item.quantity:
                remove_items[item.id] = item
        if not remove_items:
            return StandardResponse(
                status="success", message="cart is up to date", data=None
            )
        to_be_deleted_id = list(remove_items.keys())
        total_deducted = sum(i.quantity for i in remove_items.values())
        (await db.execute(delete(CartItem).where(CartItem.id.in_(to_be_deleted_id))))
        result.total_quantity = Cart.total_quantity - total_deducted
        await db.commit()
        await cart_invalidation(user_id=user_id)
    except HTTPException:
        await db.rollback()
        raise
    except IntegrityError:
        await db.rollback()
        logger.error("Database integrity error while updating cart")
        raise HTTPException(status_code=400, detail="database error")
    except Exception:
        await db.rollback()
        logger.exception("error while updating cart")
        raise HTTPException(status_code=500, detail="internal server error")
    logger.info(f"Cart with id: {cart_id} for user {user_id} successfully updated")
    return StandardResponse(
        status="success", message="cart successfully updated", data=None
    )


async def delete_one(
    store_id,
    cart_id,
    cartitem_id,
    request,
    db,
    background_task,
):
    user_id = unique_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="not authorized")
    logger.warning(f"Attempting to delete cart item {cartitem_id} from cart {cart_id}")
    try:
        stmt = (
            select(Cart, CartItem)
            .join(CartItem, Cart.id == CartItem.cart_id)
            .where(
                Cart.id == cart_id,
                CartItem.id == cartitem_id,
                Cart.store_id == store_id,
                Cart.user_id == user_id,
            )
            .with_for_update()
        )
        result = (await db.execute(stmt)).fetchone()
        if not result:
            logger.error(
                "user %s, queried a non existent cart or cartitem in delete_one function",
                user_id,
            )
            raise HTTPException(status_code=404, detail="cart or cart item not found")
        cart, delete_obj = result
        reduced_quantity = delete_obj.quantity
        await db.delete(delete_obj)
        cart.total_quantity -= reduced_quantity
        await db.commit()
    except HTTPException:
        await db.rollback()
        raise
    except IntegrityError:
        await db.rollback()
        logger.error(
            f"Database integrity error while deleting cart item {cartitem_id} from cart {cart_id} for user {user_id}"
        )
        raise HTTPException(status_code=400, detail="database error")
    except Exception:
        await db.rollback()
        logger.exception(
            f"error while deleting cart item {cartitem_id} from cart {cart_id} for user {user_id}"
        )
        raise HTTPException(status_code=500, detail="internal server error")
    background_task.add_task(cart_invalidation, user_id)
    logger.info(
        f"Cart item {cartitem_id} deleted from cart {cart_id} for user {user_id}"
    )
    return StandardResponse(status="success", message="cart item deleted", data=None)


async def delete_all(
    store_id,
    cart_id,
    request,
    db,
    background_task,
):
    user_id = unique_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="not authorized")
    logger.info(f"Attempting to delete cart {cart_id}")
    stmt = select(Cart).where(
        Cart.user_id == user_id, Cart.store_id == store_id, Cart.id == cart_id
    )
    result = (await db.execute(stmt)).scalar_one_or_none()
    if not result:
        raise HTTPException(status_code=404, detail="cart not found")
    logger.info(f"Cart {cart_id} found for user {user_id}, proceeding to delete")
    try:
        await db.delete(result)
        await db.commit()
    except IntegrityError:
        await db.rollback()
        logger.error(
            f"Database integrity error while deleting cart {cart_id} for user {user_id}"
        )
        raise HTTPException(status_code=400, detail="database error")
    except Exception:
        await db.rollback()
        logger.exception(f"error while deleting cart {cart_id} for user {user_id}")
        raise HTTPException(status_code=500, detail="internal server error")
    background_task.add_task(cart_invalidation, user_id)
    logger.info(f"Cart {cart_id} successfully deleted for user {user_id}")
    return StandardResponse(status="success", message="cart emptied", data=None)
