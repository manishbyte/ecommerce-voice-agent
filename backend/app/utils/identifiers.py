import re

CUSTOMER_ID_RE = re.compile(r"^CUS\d{4,}$")
ORDER_ID_RE = re.compile(r"^ORD\d{4,}$")
PRODUCT_ID_RE = re.compile(r"^PRD\d{4,}$")
PAYMENT_ID_RE = re.compile(r"^PAY\d{4,}$")
REFUND_ID_RE = re.compile(r"^REF\d{4,}$")
TICKET_ID_RE = re.compile(r"^TKT\d{4,}$")
ANY_ID_RE = re.compile(r"\b(?:CUS|ORD|PRD|PAY|REF|TKT|TXN|TRK|OIT)\d{4,}\b", re.I)


def find_ids(text: str, prefix: str) -> list[str]:
    return [m.upper() for m in re.findall(rf"\b{prefix}\d{{4,}}\b", text or "", flags=re.I)]


def next_business_id(prefix: str, existing_max: int | None) -> str:
    return f"{prefix}{(existing_max or 1000) + 1}"
