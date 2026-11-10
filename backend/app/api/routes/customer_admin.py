"""Customer management: create, edit, (de)activate, delete test customers, demo-data generator, change log,
and order delivery-address edits. Validation and audit logging are shared with the voice agent
(app.core.validators / app.tools.profile_tools)."""
from __future__ import annotations

import random
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import validators as v
from app.core.business_rules import INACTIVE_STATUS
from app.core.exceptions import ActionError, ValidationFailed
from app.database.base import utcnow
from app.dependencies import get_session
from app.guardrails.customer_authorization import get_owned_order
from app.models import (ChangeLog, Conversation, ConversationEvent, Customer, Message, Order, OrderItem, Payment,
                        PendingAction, Product, Refund, SupportTicket)
from app.schemas.customer import (CustomerCreate, CustomerProfile, DemoGenerateRequest, OrderAddressUpdate, ProfileUpdate)
from app.schemas.order import order_out
from app.tools.profile_tools import apply_order_address, apply_profile_changes, log_change

router = APIRouter(tags=["customer-admin"])
TEST_SOURCES = {"demo_generator", "dashboard"}      # only customers created through the app may be deleted


async def _customer(db: AsyncSession, customer_id: str) -> Customer:
    c = (await db.execute(select(Customer).where(Customer.customer_id == customer_id))).scalar_one_or_none()
    if c is None:
        raise HTTPException(404, "Customer not found")
    return c


async def _next_id(db: AsyncSession, column, prefix: str, start: int = 1001) -> str:
    last = (await db.execute(select(column).order_by(func.length(column).desc(), column.desc()).limit(1))).scalar_one_or_none()
    return f"{prefix}{int(last[len(prefix):]) + 1}" if last else f"{prefix}{start}"


# ------------------------------------------------------------------ edit
@router.patch("/customers/{customer_id}", response_model=CustomerProfile)
async def update_customer(customer_id: str, body: ProfileUpdate, db: AsyncSession = Depends(get_session)):
    """Dashboard edit (validated, change-logged). The voice agent uses the same helper after a spoken yes."""
    c = await _customer(db, customer_id)
    changes = body.model_dump(exclude_none=True)
    if "address" in changes:
        changes["address"] = {k: x for k, x in changes["address"].items() if x is not None}
    await apply_profile_changes(db, c, changes, source="dashboard", actor="recruiter")
    await db.commit()
    return CustomerProfile.model_validate(c)


@router.patch("/orders/{order_id}/address")
async def update_order_address(order_id: str, body: OrderAddressUpdate, customer_id: str = Query(...),
                               db: AsyncSession = Depends(get_session)) -> dict:
    """Change an order's delivery address - only while the order is placed/processing."""
    addr = {k: x for k, x in body.address.model_dump().items() if x is not None}
    res = await apply_order_address(db, customer_id, order_id, addr, source="dashboard", actor="recruiter")
    await db.commit()
    o = await get_owned_order(db, customer_id, order_id)
    return {**res, "order": order_out(o)}


# ------------------------------------------------------------------ create / status / delete
@router.post("/customers", response_model=CustomerProfile, status_code=201)
async def create_customer(body: CustomerCreate, db: AsyncSession = Depends(get_session)):
    errors: dict = {}
    name, e = v.validate_name(body.full_name); errors.update({"full_name": e} if e else {})
    email, e = v.validate_email(body.email); errors.update({"email": e} if e else {})
    mobile, e = v.validate_mobile(body.mobile_number); errors.update({"mobile_number": e} if e else {})
    lang, e = v.validate_language(body.preferred_language or "en-IN"); errors.update({"preferred_language": e} if e else {})
    addr, aerr = v.validate_address(body.address.model_dump(), partial_ok=False)
    errors.update(aerr)
    if errors:
        raise ValidationFailed("; ".join(f"{k}: {m}" for k, m in errors.items()))
    if (await db.execute(select(func.count()).select_from(Customer).where(func.lower(Customer.email) == email))).scalar_one():
        raise ActionError("That email address is already used by another customer.", code="email_taken")
    if (await db.execute(select(func.count()).select_from(Customer).where(Customer.mobile_number.like(f"%{mobile[-10:]}")))).scalar_one():
        raise ActionError("That mobile number is already used by another customer.", code="mobile_taken")
    cid = await _next_id(db, Customer.customer_id, "CUS")
    c = Customer(customer_id=cid, full_name=name, email=email, mobile_number=mobile, date_of_birth=body.date_of_birth,
                 status="active", address={**addr, "country": "India"}, preferred_language=lang)
    db.add(c)
    log_change(db, entity_type="customer", entity_id=cid, customer_id=cid, field="__created__", old=None, new=name,
               source="dashboard", actor="recruiter")
    await db.commit()
    return CustomerProfile.model_validate(c)


async def _set_status(db: AsyncSession, customer_id: str, status: str) -> dict:
    c = await _customer(db, customer_id)
    if c.status == status:
        return {"customer_id": customer_id, "status": status, "changed": False}
    old, c.status = c.status, status
    ended = 0
    if status == INACTIVE_STATUS:                    # a deactivated customer cannot keep an open call
        res = await db.execute(update(Conversation).where(Conversation.customer_pk == c.id, Conversation.status == "active")
                               .values(status="ended", ended_at=utcnow()))
        ended = res.rowcount or 0
    log_change(db, entity_type="customer", entity_id=customer_id, customer_id=customer_id, field="status", old=old, new=status,
               source="dashboard", actor="recruiter")
    await db.commit()
    return {"customer_id": customer_id, "status": status, "changed": True, "conversations_ended": ended}


@router.post("/customers/{customer_id}/deactivate")
async def deactivate_customer(customer_id: str, db: AsyncSession = Depends(get_session)) -> dict:
    return await _set_status(db, customer_id, INACTIVE_STATUS)


@router.post("/customers/{customer_id}/activate")
async def activate_customer(customer_id: str, db: AsyncSession = Depends(get_session)) -> dict:
    return await _set_status(db, customer_id, "active")


@router.delete("/customers/{customer_id}")
async def delete_test_customer(customer_id: str, db: AsyncSession = Depends(get_session)) -> dict:
    """Delete a customer that was created through the app (dashboard/demo generator). Seeded customers are protected."""
    c = await _customer(db, customer_id)
    created = (await db.execute(select(ChangeLog.source).where(ChangeLog.customer_id == customer_id,
                                                               ChangeLog.field == "__created__"))).scalars().first()
    if created not in TEST_SOURCES:
        raise ActionError("Only customers created from the dashboard or demo generator can be deleted. "
                          "Deactivate this customer instead.", code="protected_customer")
    convs = select(Conversation.id).where(Conversation.customer_pk == c.id)
    orders = select(Order.id).where(Order.customer_pk == c.id)
    await db.execute(delete(SupportTicket).where(SupportTicket.customer_pk == c.id))
    await db.execute(delete(PendingAction).where(PendingAction.conversation_pk.in_(convs)))
    await db.execute(delete(ConversationEvent).where(ConversationEvent.conversation_pk.in_(convs)))
    await db.execute(delete(Message).where(Message.conversation_pk.in_(convs)))
    await db.execute(delete(Conversation).where(Conversation.customer_pk == c.id))
    await db.execute(delete(Refund).where(Refund.customer_pk == c.id))
    await db.execute(delete(Payment).where(Payment.customer_pk == c.id))
    await db.execute(delete(OrderItem).where(OrderItem.order_pk.in_(orders)))
    await db.execute(delete(Order).where(Order.customer_pk == c.id))
    name = c.full_name
    await db.delete(c)
    log_change(db, entity_type="customer", entity_id=customer_id, customer_id=customer_id, field="__deleted__", old=name,
               new=None, source="dashboard", actor="recruiter")
    await db.commit()
    return {"customer_id": customer_id, "deleted": True}


# ------------------------------------------------------------------ demo data generator
_FIRST = ["Aditi", "Rohit", "Sanya", "Karan", "Neha", "Arjun", "Divya", "Manish", "Tanvi", "Yash", "Ritika", "Harsh",
          "Pallavi", "Omkar", "Shruti", "Varun", "Nandini", "Sahil", "Komal", "Tushar"]
_LAST = ["Kulkarni", "Joshi", "Patil", "Deshpande", "Mehta", "Iyer", "Nair", "Reddy", "Gupta", "Sharma", "Verma", "Shah",
         "Chavan", "More", "Pawar", "Kapoor", "Menon", "Bose", "Singh", "Rao"]
_PLACES = [("Pune", "Maharashtra", "4110"), ("Mumbai", "Maharashtra", "4000"), ("Nagpur", "Maharashtra", "4400"),
           ("Bengaluru", "Karnataka", "5600"), ("Hyderabad", "Telangana", "5000"), ("Chennai", "Tamil Nadu", "6000"),
           ("Ahmedabad", "Gujarat", "3800"), ("Jaipur", "Rajasthan", "3020"), ("Delhi", "Delhi", "1100"),
           ("Kochi", "Kerala", "6820")]
_STREETS = ["MG Road", "Station Road", "Gandhi Nagar", "Lake View Colony", "Park Street", "Temple Road", "Hill Side Layout"]


@router.post("/customers/demo")
async def generate_demo_customers(body: DemoGenerateRequest, db: AsyncSession = Depends(get_session)) -> dict:
    """Create dummy customers (and optionally orders + payments) for testing. Marked as test data (deletable)."""
    rnd = random.Random()
    products = (await db.execute(select(Product).where(Product.is_active.is_(True), Product.stock_quantity > 0))).scalars().all()
    if body.with_orders and not products:
        raise ActionError("No products in the catalogue to build demo orders from.", code="no_products")
    used_mobiles = set((await db.execute(select(Customer.mobile_number))).scalars())
    used_emails = {e.lower() for e in (await db.execute(select(Customer.email))).scalars()}
    next_cus = await _next_id(db, Customer.customer_id, "CUS")
    next_ord = await _next_id(db, Order.order_id, "ORD")
    next_pay = await _next_id(db, Payment.payment_id, "PAY")
    next_oit = await _next_id(db, OrderItem.order_item_id, "OIT")
    n = lambda s, p: int(s[len(p):])
    cus_n, ord_n, pay_n, oit_n = n(next_cus, "CUS"), n(next_ord, "ORD"), n(next_pay, "PAY"), n(next_oit, "OIT")
    today, now, created = date.today(), utcnow(), []

    for _ in range(body.count):
        first, last = rnd.choice(_FIRST), rnd.choice(_LAST)
        while True:
            mobile = f"+91{rnd.choice('6789')}{rnd.randint(0, 999999999):09d}"
            if mobile not in used_mobiles:
                break
        used_mobiles.add(mobile)
        email = f"{first}.{last}{rnd.randint(10, 999)}@demo.example.com".lower()
        while email in used_emails:
            email = f"{first}.{last}{rnd.randint(10, 9999)}@demo.example.com".lower()
        used_emails.add(email)
        city, state, pin_prefix = rnd.choice(_PLACES)
        address = {"line1": f"Flat {rnd.randint(1, 40)}, {rnd.choice(_STREETS)}", "line2": None, "city": city, "state": state,
                   "postal_code": f"{pin_prefix}{rnd.randint(0, 99):02d}", "country": "India"}
        cid = f"CUS{cus_n}"
        cus_n += 1
        cust = Customer(customer_id=cid, full_name=f"{first} {last}", email=email, mobile_number=mobile,
                        date_of_birth=date(rnd.randint(1970, 2002), rnd.randint(1, 12), rnd.randint(1, 28)), status="active",
                        address=address, preferred_language=rnd.choice(["en-IN", "hi-IN", "mr-IN"]))
        db.add(cust)
        await db.flush()
        log_change(db, entity_type="customer", entity_id=cid, customer_id=cid, field="__created__", old=None,
                   new=cust.full_name, source="demo_generator", actor="recruiter")
        orders_made = 0
        if body.with_orders:
            for k in range(rnd.choice([1, 2])):
                status = "processing" if k == 0 else rnd.choice(["shipped", "delivered"])
                lines, subtotal = [], 0
                for p in rnd.sample(products, k=min(len(products), rnd.choice([1, 2]))):
                    qty = rnd.choice([1, 1, 2])
                    lines.append((p, qty))
                    subtotal += qty * p.unit_price
                odate = today - timedelta(days=rnd.randint(1, 6))
                order = Order(order_id=f"ORD{ord_n}", customer_pk=cust.id, order_date=odate, order_status=status,
                              subtotal=subtotal, shipping_fee=0, discount_amount=0, total_amount=subtotal, currency="INR",
                              shipping_address={**address, "line1": address["line1"]},
                              estimated_delivery_date=today + timedelta(days=rnd.randint(2, 6)) if status != "delivered" else odate + timedelta(days=3),
                              delivered_at=today - timedelta(days=1) if status == "delivered" else None,
                              carrier=rnd.choice(["Delhivery", "Ecom Express", "BlueDart"]) if status != "processing" else None,
                              tracking_number=f"TRK{rnd.randint(800000, 899999)}" if status != "processing" else None,
                              scenario_note="Generated demo order")
                db.add(order)
                await db.flush()
                for p, qty in lines:
                    db.add(OrderItem(order_item_id=f"OIT{oit_n}", order_pk=order.id, product_pk=p.id, quantity=qty,
                                     unit_price=p.unit_price, line_total=qty * p.unit_price))
                    oit_n += 1
                db.add(Payment(payment_id=f"PAY{pay_n}", order_pk=order.id, customer_pk=cust.id,
                               payment_method=rnd.choice(["UPI", "credit_card", "debit_card", "net_banking"]),
                               transaction_reference=f"TXN{rnd.randint(100000, 999999)}{pay_n}", amount=subtotal, currency="INR",
                               payment_status="captured", paid_at=datetime.combine(odate, datetime.min.time()) + timedelta(hours=10)))
                log_change(db, entity_type="order", entity_id=order.order_id, customer_id=cid, field="__created__", old=None,
                           new=status, source="demo_generator", actor="recruiter")
                ord_n += 1
                pay_n += 1
                orders_made += 1
        created.append({"customer_id": cid, "full_name": cust.full_name, "mobile_number": mobile, "email": email,
                        "orders": orders_made})
    await db.commit()
    return {"created": created, "count": len(created)}


# ------------------------------------------------------------------ change log
def _log_out(r: ChangeLog) -> dict:
    return {"id": r.id, "entity_type": r.entity_type, "entity_id": r.entity_id, "customer_id": r.customer_id, "field": r.field,
            "old_value": r.old_value, "new_value": r.new_value, "source": r.source, "actor": r.actor,
            "conversation_id": r.conversation_id, "created_at": r.created_at.isoformat()}


@router.get("/changes")
async def list_changes(customer_id: str | None = Query(None), limit: int = Query(200, le=1000),
                       db: AsyncSession = Depends(get_session)) -> list[dict]:
    q = select(ChangeLog).order_by(ChangeLog.id.desc()).limit(limit)
    if customer_id:
        q = q.where(ChangeLog.customer_id == customer_id)
    return [_log_out(r) for r in (await db.execute(q)).scalars().all()]


@router.get("/customers/{customer_id}/changes")
async def customer_changes(customer_id: str, db: AsyncSession = Depends(get_session)) -> list[dict]:
    return await list_changes(customer_id=customer_id, limit=500, db=db)

