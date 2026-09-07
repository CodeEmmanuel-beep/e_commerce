from app.api.v1.schemas import (
    OrderResponse,
    PaginatedMetadata,
    StandardResponse,
)
from app.models import OrderStatus
from fastapi import APIRouter, Query, BackgroundTasks, Request, Depends
from app.services import order_service
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.get import get_db
from typing import Annotated

router = APIRouter(prefix="/order", tags=["Order"])

DatabaseDep = Annotated[AsyncSession, Depends(get_db)]


@router.post("/order/{store_id}/{order_id}")
async def create_order(
    request: Request,
    store_id: int,
    cart_id: int,
    background_tasks: BackgroundTasks,
    db: DatabaseDep,
):
    return await order_service.create_orders(
        store_id=store_id,
        cart_id=cart_id,
        background_task=background_tasks,
        db=db,
        request=request,
    )


@router.get("/order_expiration_countdown/{store_id}/{order_id}")
async def order_countdown(
    request: Request, store_id: int, order_id: int, db: DatabaseDep
):
    return await order_service.order_expiration(
        store_id=store_id, order_id=order_id, db=db, request=request
    )


@router.get(
    "/store_orders_list/{store_id}",
    response_model=StandardResponse[PaginatedMetadata[OrderResponse]],
    response_model_exclude_none=True,
    response_model_exclude_defaults=True,
)
async def store_orders(
    request: Request,
    store_id: int,
    db: DatabaseDep,
    status: OrderStatus = Query(OrderStatus.pending),
    cursor_id: int | None = Query(None, ge=1),
    limit: int = Query(10, ge=1, le=100),
):
    return await order_service.view_store_orders(
        store_id=store_id,
        db=db,
        request=request,
        status=status,
        cursor_id=cursor_id,
        limit=limit,
    )


@router.get(
    "/store_order/{store_id}/{order_id}",
    response_model=StandardResponse,
    response_model_exclude_none=True,
    response_model_exclude_defaults=True,
)
async def store_order(
    request: Request,
    store_id: int,
    order_id: int,
    db: DatabaseDep,
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
):
    return await order_service.view_store_order(
        store_id=store_id,
        order_id=order_id,
        db=db,
        request=request,
        page=page,
        limit=limit,
    )


@router.get(
    "/view_orders/{store_id}",
    response_model=StandardResponse[PaginatedMetadata[OrderResponse]],
    response_model_exclude_none=True,
    response_model_exclude_defaults=True,
)
async def view_orders(
    request: Request,
    store_id: int,
    db: DatabaseDep,
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
):
    return await order_service.view_orders(
        store_id=store_id, db=db, request=request, page=page, limit=limit
    )


@router.get(
    "/view_an_order/{store_id}/{order_id}",
    response_model=StandardResponse,
    response_model_exclude_none=True,
    response_model_exclude_defaults=True,
)
async def view_order(
    request: Request,
    store_id: int,
    order_id: int,
    db: DatabaseDep,
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
):
    return await order_service.view_order(
        store_id=store_id,
        order_id=order_id,
        db=db,
        request=request,
        page=page,
        limit=limit,
    )


@router.put("/re-order/{store_id}/{order_id}")
async def re_order(
    request: Request,
    store_id: int,
    order_id: int,
    db: DatabaseDep,
    background_task: BackgroundTasks,
):
    return await order_service.reactivate_order(
        store_id=store_id,
        order_id=order_id,
        db=db,
        request=request,
        background_task=background_task,
    )


@router.post("/order_payment/{store_id}/{order_id}")
async def proceed_to_payment(
    request: Request, store_id: int, order_id: int, db: DatabaseDep
):
    return await order_service.proceed_to_payment_portal(
        store_id=store_id, order_id=order_id, db=db, request=request
    )


@router.put(
    "/update_order_status/{store_id}/{order_id}",
    response_model=StandardResponse,
    response_model_exclude_none=True,
)
async def update_order_status(
    request: Request,
    store_id: int,
    order_id: int,
    background_task: BackgroundTasks,
    db: DatabaseDep,
    order_status: OrderStatus = Query(OrderStatus.shipped),
):
    return await order_service.toggle_status(
        store_id=store_id,
        order_id=order_id,
        status=order_status,
        background_task=background_task,
        db=db,
        request=request,
    )


@router.put(
    "/cancel_order/{store_id}/{order_id}",
    response_model=StandardResponse,
    response_model_exclude_none=True,
)
async def cancel(
    request: Request,
    store_id: int,
    order_id: int,
    db: DatabaseDep,
    background_task: BackgroundTasks,
):
    return await order_service.cancel_order(
        store_id=store_id,
        order_id=order_id,
        db=db,
        request=request,
        background_task=background_task,
    )


@router.delete(
    "/delete_order/{store_id}/{order_id}",
    response_model=StandardResponse,
    response_model_exclude_none=True,
)
async def delete_order(
    request: Request,
    store_id: int,
    order_id: int,
    db: DatabaseDep,
    background_task: BackgroundTasks,
):
    return await order_service.delete_order(
        store_id=store_id,
        order_id=order_id,
        db=db,
        request=request,
        background_task=background_task,
    )
