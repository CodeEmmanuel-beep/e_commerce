from sqlalchemy import (
    Column,
    DateTime,
    String,
    Integer,
    Float,
    ForeignKey,
    Boolean,
    Numeric,
    UniqueConstraint,
    Table,
    Enum as SQLEnum,
    LargeBinary,
    CheckConstraint,
    Text,
    Index,
    Date,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, ENUM as PG_ENUM
from enum import Enum
from sqlalchemy.orm import relationship, mapped_column, Mapped, declarative_base
from sqlalchemy.schema import Computed
from sqlalchemy import func
from decimal import Decimal
from datetime import datetime, date

Base = declarative_base()

store_staffs = Table(
    "store_staffs",
    Base.metadata,
    Column("users_id", ForeignKey("user.id"), primary_key=True),
    Column("stores_id", ForeignKey("store.id"), primary_key=True),
)
store_owners = Table(
    "store_owners",
    Base.metadata,
    Column("users_id", ForeignKey("user.id"), primary_key=True),
    Column("stores_id", ForeignKey("store.id"), primary_key=True),
)


class RoleEnum(str, Enum):
    Owner = "Owner"
    Admin = "Admin"
    user = "user"
    customer_care = "customer_care"


class BanUnit(str, Enum):
    days = "days"
    months = "months"


class User(Base):
    __tablename__ = "user"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    profile_picture: Mapped[str | None] = mapped_column(String, nullable=True)
    first_name: Mapped[str] = mapped_column(String)
    middle_name: Mapped[str | None] = mapped_column(String, nullable=True)
    surname: Mapped[str] = mapped_column(String)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    username: Mapped[str] = mapped_column(String, unique=True)
    password: Mapped[str] = mapped_column(String)
    date_of_birth: Mapped[date] = mapped_column(Date, nullable=False)
    role: Mapped[RoleEnum] = mapped_column(SQLEnum(RoleEnum), default=RoleEnum.user)
    email: Mapped[str] = mapped_column(String, unique=True)
    nationality: Mapped[str] = mapped_column(String)
    phone_number: Mapped[str | None] = mapped_column(String, nullable=True)
    address: Mapped[str | None] = mapped_column(String, nullable=True)
    is_banned: Mapped[bool] = mapped_column(Boolean, default=False)
    indefinite_ban: Mapped[bool] = mapped_column(Boolean, default=False)
    deactivation_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ban_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ban_period: Mapped[int] = mapped_column(Integer, default=0)
    ban_unit: Mapped[BanUnit | None] = mapped_column(
        SQLEnum(BanUnit), default=None, nullable=True
    )
    ban_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    ban_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index(
            "idx_deactivated_users", "id", postgresql_where=text("is_active IS False")
        ),
        Index("idx_banned_users", "id", postgresql_where=text("is_banned IS True")),
        Index(
            "idx_indefinite_ban", "id", postgresql_where=text("indefinite_ban IS True")
        ),
        CheckConstraint(
            """
        (
            -- State 1: Temp Ban -> MUST have reason, date, period, unit
            is_banned = TRUE 
            AND indefinite_ban = FALSE 
            AND ban_reason IS NOT NULL 
            AND ban_date IS NOT NULL
            AND ban_period != 0 
            AND ban_unit IS NOT NULL 
        ) 
        OR 
        (
            -- State 2: Indefinite Ban -> MUST have reason & date, MUST NOT have period/unit
            is_banned = TRUE 
            AND indefinite_ban = TRUE 
            AND ban_reason IS NOT NULL 
            AND ban_date IS NOT NULL 
            AND ban_period = 0
            AND ban_unit IS NULL
        ) 
        OR 
        (
            -- State 3: Unbanned -> MUST NOT have lingering ban_unit
            is_banned = FALSE 
            AND indefinite_ban = FALSE  
            AND ban_unit IS NULL
        )
        """,
            name="ck_user_ban_state_integrity_v2",
        ),
    )
    payments = relationship("Payment", back_populates="user")
    membership = relationship("Membership", back_populates="user")
    reviews = relationship("Review", back_populates="user")
    replies = relationship("Reply", back_populates="user")
    orders = relationship("Order", back_populates="user")
    messages = relationship("Messaging", back_populates="user")
    carts = relationship("Cart", back_populates="user")
    owners = relationship("Store", secondary=store_owners, back_populates="user_owners")
    staffs = relationship("Store", secondary=store_staffs, back_populates="user_staffs")
    reacts = relationship("React", back_populates="user")
    refunds = relationship("Refund", back_populates="user")
    created_tickets = relationship(
        "Ticket", foreign_keys="[Ticket.user_id]", back_populates="creator"
    )
    assigned_tickets = relationship(
        "Ticket", foreign_keys="[Ticket.assigned_to]", back_populates="agent"
    )


class Messaging(Base):
    __tablename__ = "message"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("user.id"), index=True)
    ticket_id: Mapped[int] = mapped_column(Integer, ForeignKey("ticket.id"), index=True)
    support_id: Mapped[int] = mapped_column(Integer, index=True)
    customer_id: Mapped[int] = mapped_column(Integer, index=True)
    message: Mapped[str | None] = mapped_column(String, nullable=True)
    photo: Mapped[str | None] = mapped_column(String, nullable=True)
    delivered: Mapped[bool] = mapped_column(Boolean, default=False)
    seen: Mapped[bool] = mapped_column(Boolean, default=False)
    sender_deleted: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    receiver_deleted: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    time_of_chat: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("idx_message_ticket_time", "ticket_id", "time_of_chat"),
        Index(
            "idx_message_customer_support", "customer_id", "support_id", "time_of_chat"
        ),
    )
    user = relationship("User", back_populates="messages")
    ticket = relationship("Ticket", back_populates="messages")


class TicketStatus(str, Enum):
    open = "open"
    in_progress = "in_progress"
    closed = "closed"


class Ticket(Base):
    __tablename__ = "ticket"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("user.id"), nullable=False)
    store_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("store.id"), nullable=False
    )
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[TicketStatus] = mapped_column(
        SQLEnum(TicketStatus), default=TicketStatus.open.value, index=True
    )
    assigned_to: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("user.id"), nullable=True, index=True
    )
    updated_at = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    store = relationship("Store", back_populates="tickets")
    creator = relationship(
        "User", foreign_keys=[user_id], back_populates="created_tickets"
    )

    agent = relationship(
        "User", foreign_keys=[assigned_to], back_populates="assigned_tickets"
    )
    messages = relationship("Messaging", back_populates="ticket")


class Store(Base):
    __tablename__ = "store"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_logo: Mapped[str | None] = mapped_column(String, nullable=True)
    store_photo: Mapped[str] = mapped_column(String, nullable=False)
    store_name: Mapped[str | None] = mapped_column(String, unique=True)
    motto: Mapped[str | None] = mapped_column(String, nullable=True)
    edited_name: Mapped[bool] = mapped_column(Boolean, default=False)
    store_previous_name: Mapped[str | None] = mapped_column(String, nullable=True)
    store_description: Mapped[str | None] = mapped_column(String, nullable=True)
    slug: Mapped[str | None] = mapped_column(String(255), nullable=False, unique=True)
    category_name: Mapped[str] = mapped_column(String, index=True)
    sub_category: Mapped[list] = mapped_column(JSONB)
    searchable_text: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed(
            "setweight(to_tsvector('english', coalesce(store_name, '')), 'A') || "
            "setweight(to_tsvector('english', coalesce(sub_category::text, '')), 'B') || "
            "setweight(to_tsvector('english', coalesce(category_name, '')), 'C')",
            persisted=True,
        ),
    )
    category_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("category.id"), index=True
    )
    avg_rating: Mapped[Decimal] = mapped_column(
        Numeric(precision=3, scale=2), default=0
    )
    review_count: Mapped[int] = mapped_column(Integer, default=0)
    store_email: Mapped[str | None] = mapped_column(String, nullable=True)
    shipping_fee: Mapped[Decimal] = mapped_column(
        Numeric(precision=10, scale=2), default=0
    )
    tax_rate: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    store_contact: Mapped[str | None] = mapped_column(String, nullable=True)
    approved: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_by: Mapped[int] = mapped_column(Integer, nullable=False)
    founded: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_by: Mapped[int] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    deleted_by: Mapped[int] = mapped_column(Integer, nullable=True)
    deleted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index(
            "idx_searchable_text",
            "searchable_text",
            postgresql_using="gin",
        ),
        Index(
            "idx_sub_category",
            "sub_category",
            postgresql_using="gin",
            postgresql_ops={"sub_category": "jsonb_path_ops"},
        ),
    )
    tickets = relationship("Ticket", back_populates="store")
    user_owners = relationship("User", secondary=store_owners, back_populates="owners")
    user_staffs = relationship("User", secondary=store_staffs, back_populates="staffs")
    category = relationship("Category", back_populates="stores")
    review = relationship("Review", back_populates="store")
    replies = relationship("Reply", back_populates="store")
    addresses = relationship("Address", back_populates="store")
    order = relationship("Order", back_populates="store", uselist=False)
    account = relationship("StoreAccount", back_populates="store")
    products = relationship("Product", back_populates="store")
    inventories = relationship("Inventory", back_populates="store")
    carts = relationship("Cart", back_populates="store")
    membership = relationship("Membership", back_populates="store", uselist=False)
    notifications = relationship("Notification", back_populates="store")
    productvariants = relationship("ProductVariant", back_populates="store")


class Address(Base):
    __tablename__ = "address"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("store.id"), index=True)
    store_address: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    street: Mapped[str] = mapped_column(String, nullable=False)
    city: Mapped[str] = mapped_column(String, nullable=False)
    state: Mapped[str] = mapped_column(String, nullable=False)
    country: Mapped[str] = mapped_column(String, nullable=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    store = relationship("Store", back_populates="addresses")
    orders = relationship("Order", back_populates="address")


class IdType(str, Enum):
    voter_id = "voter_id"
    national_id = "national_id"
    driver_license = "driver_license"
    other_id = "other_id"


class AccountType(str, Enum):
    savings = "savings"
    current = "current"
    business = "business"


class AccountVerification(str, Enum):
    pending = "pending"
    verified = "verified"
    rejected = "rejected"


class StoreAccount(Base):
    __tablename__ = "store_account"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int] = mapped_column(Integer, ForeignKey("store.id"), index=True)
    bank_name: Mapped[str] = mapped_column(String, nullable=False)
    account_holder_name: Mapped[str] = mapped_column(String, nullable=False)
    account_type: Mapped[AccountType] = mapped_column(
        SQLEnum(AccountType), default=AccountType.savings, nullable=False
    )
    type_of_id: Mapped[IdType] = mapped_column(
        SQLEnum(IdType), default=IdType.national_id, nullable=False
    )
    account_number: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    tax_identification_number: Mapped[bytes | None] = mapped_column(
        LargeBinary, nullable=True
    )
    identification_number: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    verification_status: Mapped[AccountVerification] = mapped_column(
        SQLEnum(AccountVerification), default=AccountVerification.pending, index=True
    )
    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    rejected_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    previous_rejected_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=True,
    )
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("store_id", name="unique_store_account"),
        CheckConstraint(
            "(rejected_reason IS NULL) OR (verification_status = 'rejected')",
            name="rejection_reason_check",
        ),
        CheckConstraint(
            "(verification_status != 'verified') OR (verified_at IS NOT NULL)",
            name="verified_account_timestamp_check",
        ),
    )
    store = relationship("Store", back_populates="account")


class Reply(Base):
    __tablename__ = "reply"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("user.id"), index=True)
    edited = Column(Boolean, default=False)
    review_id = Column(Integer, ForeignKey("review.id", ondelete="CASCADE"), index=True)
    product_id = Column(Integer, ForeignKey("product.id"), index=True)
    store_id = Column(Integer, ForeignKey("store.id"), index=True)
    reply_text = Column(String)
    product_reply_reaction_count: Mapped[int] = mapped_column(Integer, default=0)
    store_reply_reaction_count: Mapped[int] = mapped_column(Integer, default=0)
    time_of_post = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="replies")
    review = relationship("Review", back_populates="replies")
    product = relationship("Product", back_populates="replies")
    store = relationship("Store", back_populates="replies")
    react = relationship("React", back_populates="reply", cascade="all, delete-orphan")


class Product(Base):
    __tablename__ = "product"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int] = mapped_column(Integer, ForeignKey("store.id"))
    product_name: Mapped[str] = mapped_column(String)
    primary_image: Mapped[str] = mapped_column(String, nullable=False)
    avg_rating: Mapped[Decimal] = mapped_column(Numeric(precision=3, scale=2), default=0)
    review_count: Mapped[int] = mapped_column(Integer, default=0)
    product_description: Mapped[str] = mapped_column(Text)
    category_id: Mapped[int] = mapped_column(Integer, ForeignKey("category.id"))
    sub_category_id: Mapped[int] = mapped_column(Integer, ForeignKey("subcategory.id"))
    product_availability: Mapped[str] = mapped_column(String, default="out_of_stock")
    created_by: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    searchable_text: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed(
            "setweight(to_tsvector('english', coalesce(product_name, '')), 'A') || "
            "setweight(to_tsvector('english', coalesce(product_description, '')), 'B')",
            persisted=True,
        ),
    )
    updated_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    deleted_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    deleted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("idx_gin_searchable_text", "searchable_text", postgresql_using="gin"),
        Index(
            "idx_product_store_active",
            "store_id",
            postgresql_where=text("is_deleted IS False"),
        ),
        Index(
            "idx_product_category_active",
            "category_id",
            "sub_category_id",
            postgresql_where=text("is_deleted IS False"),
        ),
    )
    productvariants = relationship("ProductVariant", back_populates="product")
    store = relationship("Store", back_populates="products")
    review = relationship("Review", back_populates="product")
    replies = relationship("Reply", back_populates="product")
    category = relationship("Category", back_populates="products")
    sub_category = relationship("SubCategory", back_populates="products")
    notifications = relationship("Notification", back_populates="product")


class ProductVariant(Base):
    __tablename__ = "productvariant"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("product.id"), index=True
    )
    store_id: Mapped[int] = mapped_column(Integer, ForeignKey("store.id"), index=True)
    sku: Mapped[str] = mapped_column(String, index=True)
    price: Mapped[Decimal] = mapped_column(Numeric(precision=10, scale=2))
    attributes: Mapped[dict] = mapped_column(JSONB)
    created_by: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    deleted_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)

    __table_args__ = (
        Index("idx_attributes", "attributes", postgresql_using="gin"),
        UniqueConstraint("store_id", "sku", name="store_sku"),
    )
    product = relationship("Product", back_populates="productvariants")
    cartitems = relationship("CartItem", back_populates="variant")
    orderitems = relationship("OrderItem", back_populates="variant")
    store = relationship("Store", back_populates="productvariants")
    inventory = relationship("Inventory", back_populates="variant", uselist=False)
    vimage = relationship("VariantImage", back_populates="variant")
    notifications = relationship("Notification", back_populates="productvariant")

class VariantImage(Base):
    __tablename__ = "variantimage"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    variant_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("productvariant.id"), index=True
    )
    image: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    variant = relationship("ProductVariant", back_populates="vimage")


class Inventory(Base):
    __tablename__ = "inventory"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    variant_id: Mapped[int] = mapped_column(Integer, ForeignKey("productvariant.id"))
    store_id: Mapped[int] = mapped_column(Integer, ForeignKey("store.id"), index=True)
    stock_quantity: Mapped[int] = mapped_column(Integer, default=0)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    deleted_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_updated: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("store_id", "variant_id", name="uq_store_variant_inventory"),
        CheckConstraint("stock_quantity >= 0", name="positive_quantity"),
    )
    store = relationship("Store", back_populates="inventories")
    variant = relationship("ProductVariant", back_populates="inventory")


class PaymentStatus(str, Enum):
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"
    REFUNDED = "refunded"


class Payment(Base):
    __tablename__ = "payment"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("user.id"), index=True)
    order_id: Mapped[int] = mapped_column(Integer, ForeignKey("order.id"), index=True)
    payment_method: Mapped[str] = mapped_column(String)
    currency: Mapped[str] = mapped_column(String)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(precision=10, scale=2))
    total_amount: Mapped[Decimal] = mapped_column(Numeric(precision=10, scale=2))
    payment_status: Mapped[PaymentStatus] = mapped_column(
        PG_ENUM(PaymentStatus, name="paymentstatus", native_enum=True),
        default=PaymentStatus.PENDING,
        index=True,
    )
    last_event_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True, nullable=True
    )
    checkout_url: Mapped[str] = mapped_column(String, unique=True)
    reference_id: Mapped[str] = mapped_column(String, unique=True)
    transaction_id: Mapped[str | None] = mapped_column(
        String, index=True, nullable=True
    )
    discount_amount: Mapped[Decimal] = mapped_column(
        Numeric(precision=10, scale=2), default=0
    )
    shipping_fee: Mapped[Decimal] = mapped_column(
        Numeric(precision=10, scale=2), default=0
    )
    tax_rate: Mapped[float] = mapped_column(Float, default=0)
    tax_amount: Mapped[Decimal] = mapped_column(
        Numeric(precision=12, scale=2), default=0
    )
    last_event_id: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    last_updated: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    payment_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (UniqueConstraint("order_id", name="unique_order_payment"),)
    user = relationship("User", back_populates="payments")
    order = relationship("Order", back_populates="payment")
    refunds = relationship("Refund", back_populates="payment")


class Refund(Base):
    __tablename__ = "refund"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("user.id"), index=True)
    payment_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("payment.id"), index=True
    )
    order_id: Mapped[int] = mapped_column(Integer, ForeignKey("order.id"), index=True)
    refund_id: Mapped[str] = mapped_column(String, unique=True)
    refund_reason: Mapped[str] = mapped_column(String)
    refund_amount: Mapped[Decimal] = mapped_column(
        Numeric(precision=10, scale=2), default=0
    )
    last_event_id: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    last_event_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True, nullable=True
    )
    refund_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user = relationship("User", back_populates="refunds")
    order = relationship("Order", back_populates="refunds")
    payment = relationship("Payment", back_populates="refunds")


class MembershipType(str, Enum):
    Standard = "Standard"
    Regular = "Regular"
    Premium = "Premium"


class Membership(Base):
    __tablename__ = "membership"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("user.id"), index=True)
    store_id: Mapped[int] = mapped_column(Integer, ForeignKey("store.id"), index=True)
    membership_type: Mapped[MembershipType] = mapped_column(
        SQLEnum(MembershipType), default=MembershipType.Regular, index=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    delete_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reactivation_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    start_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("user_id", "store_id", name="user_store_membership"),
    )
    user = relationship("User", back_populates="membership")
    orders = relationship("Order", back_populates="membership")
    store = relationship("Store", back_populates="membership")
    carts = relationship(
        "Cart", back_populates="membership", cascade="all, delete-orphan"
    )
    subscriptions = relationship("Subscription", back_populates="membership")


class SubscriptionPlan(str, Enum):
    Standard = "Standard"
    Premium = "Premium"
    Regular = "Regular"


class SubscriptionStatus(str, Enum):
    inactive = "inactive"
    active = "active"
    past_due = "past_due"
    cancelled = "cancelled"


class Subscription(Base):
    __tablename__ = "subscription"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    membership_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("membership.id"), index=True
    )
    plan_name: Mapped[SubscriptionPlan] = mapped_column(
        SQLEnum(SubscriptionPlan),
        default=SubscriptionPlan.Standard,
        index=True,
    )
    price_id: Mapped[str | None] = mapped_column(String, nullable=True)
    plan_price: Mapped[Decimal | None] = mapped_column(
        Numeric(precision=10, scale=2), nullable=True
    )
    status: Mapped[SubscriptionStatus] = mapped_column(
        SQLEnum(SubscriptionStatus), default=SubscriptionStatus.inactive, index=True
    )
    customer_id: Mapped[str | None] = mapped_column(String, nullable=True)
    reference_id: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    last_event_id: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    last_event_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True, nullable=True
    )
    expire_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True, nullable=True
    )
    time_of_subscription: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (UniqueConstraint("membership_id", name="subscribed_member"),)
    membership = relationship("Membership", back_populates="subscriptions")


class Notification(Base):
    __tablename__ = "notification"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    notification: Mapped[str] = mapped_column(String)
    from_user: Mapped[int|None] = mapped_column(Integer, nullable=True, index=True)
    notified_user: Mapped[int] = mapped_column(Integer, index=True)
    status: Mapped[str | None] = mapped_column(String, nullable=True)
    product_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("product.id"), nullable=True
    )
    variant_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("productvariant.id"), nullable=True
    )
    store_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("store.id"), nullable=False
    )
    membership_type: Mapped[str | None] = mapped_column(String, nullable=True)
    is_active: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    is_deleted: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    time_of_op: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    product = relationship("Product", back_populates="notifications")
    productvariant = relationship("ProductVariant", back_populates="notifications")
    store = relationship("Store", back_populates="notifications")


class Review(Base):
    __tablename__ = "review"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("user.id"), index=True)
    product_id = Column(Integer, ForeignKey("product.id"), index=True)
    store_id = Column(Integer, ForeignKey("store.id"), index=True)
    review_text = Column(String)
    ratings = Column(Integer)
    product_reply_count: Mapped[int] = mapped_column(Integer, default=0)
    store_reply_count: Mapped[int] = mapped_column(Integer, default=0)
    product_review_reaction_count: Mapped[int] = mapped_column(Integer, default=0)
    store_review_reaction_count: Mapped[int] = mapped_column(Integer, default=0)
    edited = Column(Boolean, default=False)
    time_of_post = Column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    __table_args__ = (
        UniqueConstraint("user_id", "product_id", name="user_product_review"),
    )
    user = relationship("User", back_populates="reviews")
    product = relationship("Product", back_populates="review")
    store = relationship("Store", back_populates="review")
    replies = relationship(
        "Reply", back_populates="review", cascade="all, delete-orphan"
    )
    react = relationship("React", back_populates="review", cascade="all, delete-orphan")


class ReactionType(str, Enum):
    like = "like"
    love = "love"
    wow = "wow"
    laugh = "laugh"
    sad = "sad"
    angry = "angry"


class React(Base):
    __tablename__ = "react"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reaction_type: Mapped[ReactionType] = mapped_column(
        SQLEnum(ReactionType), nullable=False
    )
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("user.id"), index=True)
    reply_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("reply.id", ondelete="CASCADE"), index=True, nullable=True
    )
    review_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("review.id", ondelete="CASCADE"), index=True, nullable=True
    )
    time_of_reaction: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=func.now(), index=True
    )

    __table_args__ = (
        UniqueConstraint("user_id", "reply_id", name="unique_reply_react"),
        UniqueConstraint("user_id", "review_id", name="unique_review_react"),
        CheckConstraint(
            "(reply_id IS NULL AND review_id IS NOT NULL) OR (reply_id IS NOT NULL AND review_id IS NULL)",
            name="exactly_one_parent",
        ),
    )
    reply = relationship("Reply", back_populates="react")
    review = relationship("Review", back_populates="react")
    user = relationship("User", back_populates="reacts")


class Category(Base):
    __tablename__ = "category"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True)
    created_by: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    deleted_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    deleted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    __table_args__ = (
        Index(
            "idx_category_trgm",
            "name",
            postgresql_using="gin",
            postgresql_ops={"name": "gin_trgm_ops"},
            postgresql_where=text("is_deleted IS False"),
        ),
    )
    products = relationship("Product", back_populates="category")
    stores = relationship("Store", back_populates="category")
    sub_categories = relationship("SubCategory", back_populates="category")


class SubCategory(Base):
    __tablename__ = "subcategory"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    category_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("category.id"), index=True
    )
    name: Mapped[str] = mapped_column(String, unique=True)
    created_by: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    deleted_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    deleted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    __table_args__ = (
        Index(
            "idx_subcategory_trgm",
            "name",
            postgresql_using="gin",
            postgresql_ops={"name": "gin_trgm_ops"},
            postgresql_where=text("is_deleted IS False"),
        ),
    )
    products = relationship("Product", back_populates="sub_category")
    category = relationship("Category", back_populates="sub_categories")


class CartItem(Base):
    __tablename__ = "cartitem"
    id = Column(Integer, primary_key=True)
    cart_id = Column(Integer, ForeignKey("cart.id", ondelete="CASCADE"), index=True)
    quantity = Column(Float, default=1)
    variant_id = Column(Integer, ForeignKey("productvariant.id"), index=True)

    variant = relationship("ProductVariant", back_populates="cartitems")
    cart = relationship("Cart", back_populates="cartitems")


class Cart(Base):
    __tablename__ = "cart"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("user.id"), index=True)
    store_id = Column(Integer, ForeignKey("store.id"), index=True)
    member_id = Column(
        Integer, ForeignKey("membership.id", ondelete="CASCADE"), index=True
    )
    check_out: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    total_quantity = Column(Float, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    user = relationship("User", back_populates="carts")
    store = relationship("Store", back_populates="carts")
    cartitems = relationship(
        "CartItem", back_populates="cart", cascade="all, delete-orphan"
    )
    membership = relationship("Membership", back_populates="carts")


class OrderStatus(str, Enum):
    pending = "pending"
    processing = "processing"
    paid = "paid"
    shipped = "shipped"
    delivered = "delivered"
    cancelled = "cancelled"


class Order(Base):
    __tablename__ = "order"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("user.id"), index=True)
    store_id: Mapped[int] = mapped_column(Integer, ForeignKey("store.id"), index=True)
    delivery_address_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("address.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    member_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("membership.id"), index=True, nullable=True
    )
    total_quantity: Mapped[float] = mapped_column(Float, default=0)
    delivery_address: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    order_delete: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[OrderStatus] = mapped_column(
        SQLEnum(OrderStatus),
        default=OrderStatus.pending,
        nullable=False,
        index=True,
    )
    subtotal: Mapped[Decimal] = mapped_column(Numeric(precision=12, scale=2), default=0)
    total_amount: Mapped[Decimal] = mapped_column(
        Numeric(precision=12, scale=2), default=0
    )
    tax_rate: Mapped[float] = mapped_column(Float, default=0)
    tax_amount: Mapped[Decimal] = mapped_column(
        Numeric(precision=12, scale=2), default=0
    )
    shipping_fee: Mapped[Decimal] = mapped_column(
        Numeric(precision=12, scale=2), default=0
    )
    discount_amount: Mapped[Decimal] = mapped_column(
        Numeric(precision=12, scale=2), default=0
    )
    reference_id: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)
    re_order_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True, nullable=False
    )

    payment = relationship("Payment", back_populates="order", uselist=False)
    refunds = relationship("Refund", back_populates="order")
    user = relationship("User", back_populates="orders")
    orderitems = relationship("OrderItem", back_populates="order")
    membership = relationship("Membership", back_populates="orders")
    store = relationship("Store", back_populates="order")
    address = relationship("Address", back_populates="orders")


class OrderItem(Base):
    __tablename__ = "orderitem"
    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey("order.id"), index=True)
    variant_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("productvariant.id"), index=True
    )
    quantity = Column(Float, default=1)
    price = Column(Numeric(precision=12, scale=2))

    variant = relationship("ProductVariant", back_populates="orderitems")
    order = relationship("Order", back_populates="orderitems")
