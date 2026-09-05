from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    model_validator,
    field_validator,
    ValidationInfo,
    field_serializer,
)
from typing import TypeVar, Generic, Any
from datetime import datetime, date
from app.utils.supabase_url import get_public_url
from decimal import Decimal
from enum import Enum
import re

T = TypeVar("T")


class LoginResponse(BaseModel):
    username: str
    password: str

    model_config = ConfigDict(from_attributes=True)


class QueryEnum(str, Enum):
    Yes = "Yes"
    No = "No"


class ProductSearch(str, Enum):
    product_name = "product_name"
    category = "category"
    sub_category = "sub_category"


class ChronologyEnum(str, Enum):
    desc = "desc"
    asc = "asc"


class AddSwapEnum(str, Enum):
    add = "add"
    swap = "swap"


class UserState(str, Enum):
    is_banned = "is_banned"
    not_active = "not_active"
    new_users = "new_users"


class StoreFilterEnum(str, Enum):
    store = "store"
    product = "product"


class OwnerStaff(str, Enum):
    owner = "owner"
    staff = "staff"


class RankingEnum(str, Enum):
    top_product = "top_product"
    least_product = "least_product"


class ProductStatisticsEnum(str, Enum):
    product_ratings = "product_ratings"
    product_sales = "product_sales"


class StockRangeEnum(str, Enum):
    thirty_below = "thirty_below"
    five_below = "five_below"
    twenty_below = "twenty_below"
    fifty_below = "fifty_below"
    out_of_stock = "out_of_stock"
    above_fifty = "above_fifty"
    ten_below = "ten_below"


class SupportCustomerEnum(str, Enum):
    customer_view = "customer_view"
    support_view = "support_view"


class ProductFilterEnum(str, Enum):
    latest = "latest"
    quality = "quality"


class TimeFrameEnum(str, Enum):
    one_week = "1 week"
    one_month = "1 month"
    three_months = "3 months"
    six_months = "6 months"
    one_year = "1 year"
    total = "total"


class SubscriptionTypeEnum(str, Enum):
    one_time = "one_time"
    subscription = "subscription"


class PersonnelResponse(BaseModel):
    id: int
    profile_picture: str | None = None
    first_name: str
    middle_name: str | None = None
    surname: str
    phone_number: str | None = None
    email: str | None = None

    @field_validator("profile_picture", mode="before")
    @classmethod
    def render_picture(cls, value) -> str | None:
        if value:
            return get_public_url(value)

    model_config = ConfigDict(from_attributes=True)


class ProfileResponse(BaseModel):
    id: int
    profile_picture: str | None = None
    role: str = Field(default="user")
    first_name: str
    middle_name: str | None = None
    surname: str

    @field_validator("profile_picture", mode="before")
    @classmethod
    def render_picture(cls, value) -> str | None:
        if value:
            return get_public_url(value)

    model_config = ConfigDict(from_attributes=True)


class UserResponse(BaseModel):
    id: int
    profile_picture: str | None = None
    first_name: str
    middle_name: str | None = None
    surname: str
    username: str
    role: str = Field(default="user")
    age: int = Field(default_factory=int)
    date_of_birth: date
    phone_number: str | None = None
    email: str
    nationality: str
    address: str | None = None

    model_config = ConfigDict(from_attributes=True)


class ProductVariantRequest(BaseModel):
    id: int | None = None
    store_id: int
    product_id: int | None = None
    attributes: dict | Any | None = None
    sku: str | None = None
    price: Decimal | None = None


class StoreAccountsList(BaseModel):
    id: int
    bank_name: str
    account_type: str
    account_holder_name: str
    account_number: str
    type_of_id: str
    identification_number: str
    tax_identification_number: str | None = None
    submitted_at: datetime | None = None
    updated_at: datetime | None = None
    verification_status: str = Field(default="pending")
    verified_at: datetime | None = None
    rejected_reason: str | None = None
    previous_rejected_reason: str | None = None

    @model_validator(mode="before")
    @classmethod
    def decryption(cls, data: Any, info: ValidationInfo) -> Any:
        context = info.context
        if not context:
            raise ValueError("Validation context is missing. Cannot decrypt data.")
        cipher = context.get("cipher")
        if not cipher:
            raise ValueError("cipher key not found")
        sensitive_fields = [
            "account_number",
            "tax_identification_number",
            "identification_number",
        ]
        for field in sensitive_fields:
            value = (
                data.get(field, None)
                if isinstance(data, dict)
                else getattr(data, field, None)
            )
            if value is None:
                continue
            try:
                decrypted_field = cipher.decrypt(value).decode()
                if isinstance(data, dict):
                    data[field] = decrypted_field
                else:
                    setattr(data, field, decrypted_field)
            except Exception:
                raise ValueError("error decrypting sensitive field: %s", field)
        return data

    model_config = ConfigDict(from_attributes=True)


class SuperUserResponse(BaseModel):
    id: int
    is_active: bool
    profile_picture: str | None = None
    first_name: str
    middle_name: str | None = None
    surname: str
    username: str
    role: str = Field(default="user")
    age: int = Field(default_factory=int)
    date_of_birth: date
    phone_number: str | None = None
    email: str
    nationality: str
    address: str | None = None
    deactivation_time: datetime | None = None
    is_banned: bool
    indefinite_ban: bool | None = None
    ban_count: int
    ban_date: datetime | None = None
    ban_reason: str | None = None
    ban_period: int
    ban_unit: str | None = None

    model_config = ConfigDict(from_attributes=True)


class NotificationResponse(BaseModel):
    id: int
    notification: str
    product_name: str | None = Field(default_factory=str)
    store_name: str | None = Field(default_factory=str)
    membership_type: str | None = None
    status: str | None = None
    is_active: bool | None = None
    is_deleted: bool | None = None
    is_read: bool = Field(default=False)
    time_of_op: datetime | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class StoreAccountResponse(BaseModel):
    id: int
    bank_name: str
    account_type: str
    account_holder_name: str
    account_number: str
    type_of_id: str
    identification_number: str
    tax_identification_number: str | None = None
    verification_status: str = Field(default="pending")
    rejected_reason: str | None = None

    @model_validator(mode="before")
    @classmethod
    def decryption(cls, data: Any, info: ValidationInfo) -> Any:
        context = info.context
        if not context:
            raise ValueError("Validation context is missing. Cannot decrypt data.")
        cipher = context.get("cipher")
        if not cipher:
            raise ValueError("cipher key not found")
        sensitive_fields = [
            "account_number",
            "tax_identification_number",
            "identification_number",
        ]
        for field in sensitive_fields:
            value = (
                data.get(field, None)
                if isinstance(data, dict)
                else getattr(data, field, None)
            )
            if value is None:
                continue
            try:
                decrypted_field = cipher.decrypt(value).decode()
                if isinstance(data, dict):
                    data[field] = decrypted_field
                else:
                    setattr(data, field, decrypted_field)
            except Exception:
                raise ValueError("error decrypting sensitive field: %s", field)
        return data

    model_config = ConfigDict(from_attributes=True)


class AddressDetails(BaseModel):
    street: str
    city: str
    state: str
    country: str


class AddressResponse(BaseModel):
    id: int
    street: str
    city: str
    state: str
    country: str

    model_config = ConfigDict(from_attributes=True)


class ReactionType(str, Enum):
    like = "like"
    love = "love"
    laugh = "laugh"
    wow = "wow"
    sad = "sad"
    angry = "angry"


class ReactionsSummary(BaseModel):
    like: int = 0
    love: int = 0
    laugh: int = 0
    wow: int = 0
    sad: int = 0
    angry: int = 0


class PaginatedResponse(BaseModel):
    page: int
    limit: int
    total: int


class MemberStatus(str, Enum):
    active_members = "active_members"
    inactive_members = "inactive_members"
    deleted_members = "deleted_members"


class CursorPaginatedResponse(BaseModel):
    next_cursor: int | None = None
    limit: int
    has_more: bool


class PaginatedMetadata(BaseModel, Generic[T]):
    items: list[T]
    pagination: PaginatedResponse | None = None
    cursor_pagination: CursorPaginatedResponse | None = None


class StandardResponse(BaseModel, Generic[T]):
    status: str
    message: str
    data: T | None = None


class ReplyResponse(BaseModel):
    id: int
    edited: bool = Field(default=False)
    user: ProfileResponse
    reply_text: str
    store_reply_reaction_count: int = Field(default=0)
    product_reply_reaction_count: int = Field(default=0)
    reactions: ReactionsSummary = Field(default_factory=ReactionsSummary)
    time_of_post: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class Reply(BaseModel):
    id: int | None = None
    store_id: int
    product_id: int | None = None
    review_id: int | None = None
    reply_text: str


class Chat(BaseModel):
    id: int
    ticket_id: int
    ticket_status: str = Field(default_factory=str)
    unread_count: int = Field(default_factory=int)
    customer_photo: str = Field(default_factory=str)
    customer: str = Field(default_factory=str)
    store_photo: str = Field(default_factory=str)
    customer_support: str = Field(default_factory=str)
    sender: str = Field(default_factory=str)
    photo: str | None = None
    message: str | None = None
    delivered: bool = Field(default=False)
    seen: bool = Field(default=False)
    time_of_chat: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class InventoryObj(BaseModel):
    stock_quantity: int

    model_config = ConfigDict(from_attributes=True)


class ProductVariantResponse(BaseModel):
    id: int
    product_id: int
    primary_image: str | None = None
    attributes: dict | Any
    sku: str
    price: Decimal
    inventory: InventoryObj | None = None

    model_config = ConfigDict(from_attributes=True)


class ProductImageResponse(BaseModel):
    id: int
    image: str

    @model_validator(mode="before")
    @classmethod
    def render_urls(cls, value: Any) -> Any:
        file = "image"
        if isinstance(value, dict):
            v = value.get(file, None)
        else:
            v = getattr(value, file, None)
        try:
            rendered = get_public_url(v)
            if isinstance(value, dict):
                value[file] = rendered
            else:
                setattr(value, file, rendered)
        except Exception as e:
            raise ValueError(
                f"could not render image url for field '{file}' with value '{v}': {e}"
            )
        return value

    model_config = ConfigDict(from_attributes=True)


class VariantInventoryResponse(BaseModel):
    id: int
    sku: str

    model_config = ConfigDict(from_attributes=True)


class InventoryResponse(BaseModel):
    id: int
    variant: VariantInventoryResponse
    stock_quantity: int
    last_updated: datetime

    model_config = ConfigDict(from_attributes=True)


class Cart_Order_Variant_Response(BaseModel):
    id: int
    store_id: int
    attributes: dict | Any
    sku: str
    price: Decimal

    model_config = ConfigDict(from_attributes=True)


class StoreRes(BaseModel):
    id: int
    business_logo: str | None = None
    store_photo: str
    store_name: str

    @field_serializer("business_logo", "store_photo", mode="plain")
    @classmethod
    def resolve_public_url(cls, value: str | None = None) -> str | None:
        if not value:
            return None
        if value.startswith(("http://", "https://")):
            return value
        return get_public_url(value)

    model_config = ConfigDict(from_attributes=True)


class ProductRes(BaseModel):
    id: int
    store_id: int
    product_name: str
    primary_image: str
    product_availability: str
    avg_rating: Decimal = Field(default=Decimal("0.00"))

    @field_validator("primary_image", mode="before")
    @classmethod
    def full_url(cls, value) -> str | None:
        return get_public_url(value)

    model_config = ConfigDict(from_attributes=True)


class SingleProductResponse(BaseModel):
    store: StoreRes | None = None
    id: int
    product_name: str
    primary_image: str
    avg_rating: Decimal = Field(default=Decimal("0.00"))
    review_count: int = Field(default=0)
    product_description: str
    product_availability: str
    productvariants: list | None = None

    @field_validator("primary_image", mode="before")
    @classmethod
    def full_url(cls, value) -> str | None:
        return get_public_url(value)

    model_config = ConfigDict(from_attributes=True)


class ProductResponse(BaseModel):
    id: int
    product_name: str
    primary_image: str
    avg_rating: Decimal = Field(default=Decimal("0.00"))
    review_count: int = Field(default=0)
    product_description: str
    product_availability: str

    @field_validator("primary_image", mode="before")
    @classmethod
    def full_url(cls, value) -> str | None:
        return get_public_url(value)

    model_config = ConfigDict(from_attributes=True)


class PersonalStoreResponse(BaseModel):
    id: int
    business_logo: str | None = None
    store_photo: str | None = None
    store_name: str
    category_name: str
    sub_category: list[str]
    store_previous_name: str | None = None
    store_contact: str | None = None
    store_email: str | None = None
    avg_rating: Decimal = Field(default=Decimal("0.00"))
    review_count: int = Field(default=0)
    motto: str | None = None
    tax_rate: float = Field(default=0)
    shipping_fee: Decimal
    store_description: str | None = None
    approved: bool = Field(default=False)
    founded: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class StoreResponse(BaseModel):
    id: int
    business_logo: str | None = None
    store_photo: str
    store_name: str
    category_name: str
    sub_category: list[str]
    store_previous_name: str | None = None
    review_count: int = Field(default=0)
    avg_rating: Decimal = Field(default=Decimal("0.00"))
    motto: str | None = None
    featured_product: list[ProductRes] | ProductRes = Field(default_factory=list)
    shipping_fee: Decimal
    store_description: str | None = None
    founded: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class ReactResponse(BaseModel):
    id: int
    user: ProfileResponse
    reaction_type: str
    time_of_reaction: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class ProfileMode(BaseModel):
    first_name: str | None = None
    middle_name: str | None = None
    surname: str | None = None
    email: str | None = None
    nationality: str | None = None
    phone_number: str | None = None
    address: str | None = None


class RegistrationModel(BaseModel):
    first_name: str = Field(..., min_length=1, max_length=50)
    surname: str = Field(..., min_length=1, max_length=50)
    username: str
    email: str
    date_of_birth: date
    nationality: str
    address: str | None = None
    password: str = Field(
        ..., min_length=8, description="Password must be at least 8 characters"
    )
    confirm_password: str

    @field_validator("password")
    @classmethod
    def validate_password_complexity(cls, value: str) -> str:
        if not re.search(r"[A-Za-z]", value):
            raise ValueError("Password must contain at least one letter")
        if not re.search(r"\d", value):
            raise ValueError("Password must contain at least one digit")
        if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", value):
            raise ValueError("Password must contain at least one special character")
        return value

    @field_validator("date_of_birth")
    @classmethod
    def validate_age(cls, value: date) -> date:
        today = date.today()
        if value >= today:
            raise ValueError("Date of birth must be in the past")
        age = (
            today.year
            - value.year
            - ((today.month, today.day) < (value.month, value.day))
        )
        if age < 13:
            raise ValueError("User must be at least 13 years old to register")
        return value


class PaymentResponse(BaseModel):
    id: int
    order_id: int
    payment_method: str
    currency: str
    payment_status: str
    subtotal: Decimal
    shipping_fee: Decimal
    tax_amount: Decimal
    discount_amount: Decimal
    total_amount: Decimal
    total_refund: Decimal | None = Field(default_factory=Decimal)
    reference_id: str
    transaction_id: str | None = None
    payment_date: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class SubscriptionResponse(BaseModel):
    id: int
    membership_id: int
    plan_name: str
    price_id: str | None
    plan_price: Decimal | None
    status: str
    expire_at: datetime | None = None
    time_of_subscription: datetime

    model_config = ConfigDict(from_attributes=True)


class ProductReviewResponse(BaseModel):
    id: int
    store_id: int | None = None
    product_id: int
    user: ProfileResponse
    edited: bool = Field(default=False)
    review_text: str
    ratings: int
    product_reply_count: int = Field(default=0)
    product_review_reaction_count: int = Field(default=0)
    reactions: ReactionsSummary = Field(default_factory=ReactionsSummary)
    time_of_post: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class StoreReviewResponse(BaseModel):
    id: int
    store_id: int
    user: ProfileResponse
    edited: bool = Field(default=False)
    ratings: int
    review_text: str
    store_reply_count: int = Field(default=0)
    store_review_reaction_count: int = Field(default=0)
    reactions: ReactionsSummary = Field(default_factory=ReactionsSummary)
    time_of_post: datetime

    model_config = ConfigDict(from_attributes=True)


class Review(BaseModel):
    id: int | None = None
    product_id: int | None = None
    store_id: int
    review_text: str


class CategoryResponse(BaseModel):
    id: int
    name: str

    model_config = ConfigDict(from_attributes=True)


class SubCategoryResponse(BaseModel):
    id: int
    category_id: int
    name: str

    model_config = ConfigDict(from_attributes=True)


class CartItemReponse(BaseModel):
    id: int
    variant: Cart_Order_Variant_Response
    quantity: int

    model_config = ConfigDict(from_attributes=True)


class CartResponse(BaseModel, Generic[T]):
    id: int
    items: list[CartItemReponse] = Field(default_factory=list)
    total_quantity: float
    check_out: bool = Field(default=False)
    created_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class Orders(BaseModel):
    order_id: int
    product_id: int
    quantity: float
    price: float


class MemRes(BaseModel):
    membership_type: str

    model_config = ConfigDict(from_attributes=True)


class OrderItemRes(BaseModel):
    variant: Cart_Order_Variant_Response
    quantity: float
    price: Decimal

    model_config = ConfigDict(from_attributes=True)


class OrderResponse(BaseModel):
    user: ProfileResponse
    id: int
    membership: MemRes | None = None
    tax_rate: float
    tax_amount: Decimal
    shipping_fee: Decimal
    discount_amount: Decimal
    total_quantity: float
    subtotal: Decimal
    total_amount: Decimal
    status: str
    delivery_address: list | None = None
    created_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class MembershipResponse(BaseModel):
    id: int
    membership_type: str
    is_active: bool = Field(default=False)
    start_date: datetime

    @computed_field
    def offer_status(self) -> str:
        if not self.is_active:
            return "must be an active member to receive a membership discount"
        discounts = {"Regular": "1%", "Standard": "2%", "Premium": "3%"}
        rate = discounts.get(self.membership_type, "0%")
        return f"{rate} discount on every purchase"

    model_config = ConfigDict(from_attributes=True)


class MembershipRes(BaseModel):
    user: ProfileResponse
    id: int
    membership_type: str
    start_date: datetime
    pause_date: datetime | None = None
    reativation_data: datetime | None = None
    delete_date: datetime | None = None

    model_config = ConfigDict(from_attributes=True)
