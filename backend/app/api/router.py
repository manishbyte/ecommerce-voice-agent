from fastapi import APIRouter

from app.api.routes import (conversations, customer_admin, customers, evaluations, health, orders, payments, products, refunds,
                            tickets, voice)

api_router = APIRouter(prefix="/api")
for module in (health, customers, customer_admin, products, orders, payments, refunds, tickets, conversations, voice, evaluations):
    api_router.include_router(module.router)
