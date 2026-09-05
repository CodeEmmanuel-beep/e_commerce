from app.api.v1.schemas import (
    StandardResponse,
)
from fastapi import APIRouter, Query, Request, Depends, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from app.services import cart_service
from app.database.get import get_db
from typing import Annotated

router = APIRouter(prefix="/cart", tags=["Cart"])

DatabaseDep = Annotated[AsyncSession, Depends(get_db)]


@router.post(
    "/add_to_cart",
    response_model=StandardResponse,
    response_model_exclude_none=True,
)
async def add_cartitem(
    store_id: int,
    variant_id: int,
    request: Request,
    db: DatabaseDep,
    background_task: BackgroundTasks,
    quantity: int = Query(1, ge=1),
):
    return await cart_service.add_item_to_cart(
        store_id=store_id,
        variant_id=variant_id,
        request=request,
        quantity=quantity,
        background_task=background_task,
        db=db,
    )


@router.get(
    "/fetch_cart",
    response_model=StandardResponse,
    response_model_exclude_none=True,
    response_model_exclude_defaults=True,
)
async def get_cart(
    store_id: int,
    request: Request,
    db: DatabaseDep,
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
):
    return await cart_service.retrieve_cart(
        store_id=store_id,
        request=request,
        db=db,
        page=page,
        limit=limit,
    )


@router.put(
    "/edit_quantity",
    response_model=StandardResponse,
    response_model_exclude_none=True,
)
async def change_quanity(
    store_id: int,
    cart_id: int,
    cartitem_id: int,
    request: Request,
    db: DatabaseDep,
    new_quantity: int = Query(1, ge=1),
):
    return await cart_service.edit_quantity(
        cart_id=cart_id,
        store_id=store_id,
        cartitem_id=cartitem_id,
        request=request,
        new_quantity=new_quantity,
        db=db,
    )


@router.put(
    "/update_cart/{store_id}/{cart_id}",
    response_model=StandardResponse,
    response_model_exclude_none=True,
)
async def update__cart(store_id: int, cart_id: int, request: Request, db: DatabaseDep):
    return await cart_service.update_cart(
        request=request, cart_id=cart_id, store_id=store_id, db=db
    )


@router.delete(
    "/delete_cartitem",
    response_model=StandardResponse,
    response_model_exclude_none=True,
)
async def delete_one(
    store_id: int,
    cart_id: int,
    cartitem_id: int,
    request: Request,
    db: DatabaseDep,
    background_task: BackgroundTasks,
):
    return await cart_service.delete_one(
        cart_id=cart_id,
        store_id=store_id,
        cartitem_id=cartitem_id,
        db=db,
        request=request,
        background_task=background_task,
    )


@router.delete(
    "/delete_cart/{store_id}/{cart_id}",
    response_model=StandardResponse,
    response_model_exclude_none=True,
)
async def delete_cart(
    store_id: int,
    cart_id: int,
    request: Request,
    db: DatabaseDep,
    background_task: BackgroundTasks,
):
    return await cart_service.delete_all(
        cart_id=cart_id,
        store_id=store_id,
        request=request,
        db=db,
        background_task=background_task,
    )
