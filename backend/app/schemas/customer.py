from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.utils.identifiers import CUSTOMER_ID_RE


class AddressSchema(BaseModel):
    line1: str
    line2: str | None = None
    city: str
    state: str
    postal_code: str
    country: str = "India"


class CustomerSeed(BaseModel):
    customer_id: str
    full_name: str
    email: str
    mobile_number: str
    date_of_birth: date | None = None
    status: str = "active"
    address: AddressSchema
    preferred_language: str | None = None
    created_at: datetime

    def model_post_init(self, _ctx) -> None:
        if not CUSTOMER_ID_RE.match(self.customer_id):
            raise ValueError(f"bad customer_id {self.customer_id}")


class CustomerSummary(BaseModel):
    customer_id: str
    full_name: str
    mobile_number: str
    email: str
    status: str
    city: str | None = None
    total_orders: int = 0
    active_complaints: int = 0
    preferred_language: str | None = None


class CustomerProfile(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    customer_id: str
    full_name: str
    email: str
    mobile_number: str
    date_of_birth: date | None = None
    status: str
    address: dict
    preferred_language: str | None = None
    created_at: datetime


class CustomerDetail(BaseModel):
    profile: CustomerProfile
    orders: list = Field(default_factory=list)
    payments: list = Field(default_factory=list)
    refunds: list = Field(default_factory=list)
    tickets: list = Field(default_factory=list)


# ---------------------------------------------------------------- edit / create / demo-data schemas
class AddressIn(BaseModel):
    line1: str | None = None
    line2: str | None = None
    city: str | None = None
    state: str | None = None
    postal_code: str | None = None


class ProfileUpdate(BaseModel):
    """Any subset of editable profile fields. Validation lives in app.core.validators (shared with the voice agent)."""
    full_name: str | None = None
    email: str | None = None
    mobile_number: str | None = None
    preferred_language: str | None = None
    address: AddressIn | None = None


class CustomerCreate(BaseModel):
    full_name: str
    email: str
    mobile_number: str
    preferred_language: str | None = "en-IN"
    date_of_birth: date | None = None
    address: AddressIn


class OrderAddressUpdate(BaseModel):
    address: AddressIn


class DemoGenerateRequest(BaseModel):
    count: int = Field(default=3, ge=1, le=25)
    with_orders: bool = True
