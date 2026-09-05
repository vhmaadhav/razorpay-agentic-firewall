"""Pydantic models mirroring 03-canonical-authorization-schema.md."""
from __future__ import annotations

from pydantic import BaseModel, Field


class Principal(BaseModel):
    user_id: str
    identity_provider: str = "razorpay"


class Agent(BaseModel):
    agent_id: str
    provider: str
    public_key: str
    trust_level: str = "user_key"


class MerchantScope(BaseModel):
    merchant_ids: list[str] = Field(default_factory=list)
    merchant_categories: list[str] = Field(default_factory=list)


class ProductScope(BaseModel):
    allowed_skus: list[str] = Field(default_factory=list)
    allowed_categories: list[str] = Field(default_factory=list)
    forbidden_skus: list[str] = Field(default_factory=list)
    substitutions_allowed: bool = False


class FinancialScope(BaseModel):
    currency: str = "INR"
    max_total: int
    max_unit_price: int | None = None
    shipping_included: bool = True
    tax_included: bool = True
    tips_allowed: bool = False


class QuantityScope(BaseModel):
    max_items: int


class TemporalScope(BaseModel):
    issued_at: str
    expires_at: str


class ExecutionScope(BaseModel):
    max_transactions: int = 1
    reusable: bool = False


class CanonicalAuthorizationEnvelope(BaseModel):
    version: str = "1.0"
    authorization_id: str
    principal: Principal
    agent: Agent
    merchant_scope: MerchantScope
    product_scope: ProductScope
    financial_scope: FinancialScope
    quantity_scope: QuantityScope
    temporal_scope: TemporalScope
    execution_scope: ExecutionScope
    nonce: str
    evidence_hash: str = ""
    signature: str | None = None

    def unsigned_dict(self) -> dict:
        """Fields that go into evidence_hash (excludes evidence_hash/signature)."""
        return self.model_dump(exclude={"evidence_hash", "signature"})


class CartItem(BaseModel):
    sku: str
    unit_price: int
    quantity: int
    category: str | None = None


class Cart(BaseModel):
    merchant_id: str
    items: list[CartItem]
    shipping: int = 0
    tax: int = 0
    total: int
    currency: str = "INR"


class AgentRequest(BaseModel):
    authorization_id: str
    nonce: str
    agent_id: str
    cart: Cart
    agent_signature: str | None = None
