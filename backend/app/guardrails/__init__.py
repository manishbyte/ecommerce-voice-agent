from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class GuardrailResult:
    passed: bool = True
    code: str = "ok"
    message: str = ""
    details: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"passed": self.passed, "code": self.code, "message": self.message, "details": self.details}
