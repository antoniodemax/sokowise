"""Receipt extraction: image → structured, untrusted proposal (docs/ARCHITECTURE.md §6.7).

`ReceiptExtractionProvider` is the only thing the rest of the system talks to. The
Anthropic implementation forces a tool call whose input schema *is* the contract,
so the model can return nothing but the fields below; every value is then
re-validated by the backend before anyone sees it. Nothing here touches the
database, and no business or customer data is sent with the image.
"""

import base64
import logging
from datetime import date
from decimal import Decimal
from typing import Any, Protocol

import anthropic
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.ai.errors import AIUnavailableError
from app.core.config import Settings

logger = logging.getLogger(__name__)

RECEIPT_MODEL_MAX_TOKENS = 4000
MAX_LINES = 60


class ExtractedLine(BaseModel):
    """One purchased line as printed on the receipt."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    product_name: str = Field(min_length=1, max_length=160)
    sku: str | None = Field(default=None, max_length=64)
    quantity: Decimal = Field(gt=0, max_digits=12, decimal_places=3)
    unit_cost: Decimal = Field(ge=0, max_digits=14, decimal_places=2)
    line_total: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    confidence: Decimal | None = Field(default=None, ge=0, le=1, max_digits=4, decimal_places=3)


class ReceiptExtraction(BaseModel):
    """The whole structured result. Optional fields are null when not printed."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    supplier_name: str | None = Field(default=None, max_length=120)
    receipt_number: str | None = Field(default=None, max_length=64)
    receipt_date: date | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    subtotal: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    total: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    lines: list[ExtractedLine] = Field(max_length=MAX_LINES)


class ExtractionResult(BaseModel):
    """What a provider returns: the validated extraction plus provenance for the audit row."""

    extraction: ReceiptExtraction
    provider: str
    model: str | None = None


class ReceiptExtractionError(AIUnavailableError):
    """The provider answered, but not with a usable receipt (unreadable image, bad shape)."""

    code = "RECEIPT_EXTRACTION_FAILED"


class ReceiptExtractionProvider(Protocol):
    async def extract(self, image: bytes, *, mime_type: str) -> ExtractionResult: ...


# --- Anthropic ---------------------------------------------------------------------------

RECEIPT_TOOL = {
    "name": "record_receipt",
    "description": (
        "Record the contents of a supplier receipt or invoice exactly as printed. Use null "
        "for anything not visible. quantity and unit_cost are numbers as printed; line_total "
        "is the printed line amount, never computed. Do not invent products, prices or dates."
    ),
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "supplier_name",
            "receipt_number",
            "receipt_date",
            "currency",
            "subtotal",
            "total",
            "lines",
        ],
        "properties": {
            "supplier_name": {"type": ["string", "null"]},
            "receipt_number": {"type": ["string", "null"]},
            "receipt_date": {
                "type": ["string", "null"],
                "description": "ISO date YYYY-MM-DD if printed",
            },
            "currency": {"type": ["string", "null"], "description": "ISO 4217, e.g. KES"},
            "subtotal": {"type": ["string", "null"], "description": "decimal as a string"},
            "total": {"type": ["string", "null"], "description": "decimal as a string"},
            "lines": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "product_name",
                        "sku",
                        "quantity",
                        "unit_cost",
                        "line_total",
                        "confidence",
                    ],
                    "properties": {
                        "product_name": {"type": "string"},
                        "sku": {"type": ["string", "null"]},
                        "quantity": {"type": "string", "description": "decimal as a string"},
                        "unit_cost": {"type": "string", "description": "decimal as a string"},
                        "line_total": {"type": ["string", "null"]},
                        "confidence": {
                            "type": ["string", "null"],
                            "description": "0 to 1, how legible this line was",
                        },
                    },
                },
            },
        },
    },
    "strict": True,
}

RECEIPT_PROMPT = (
    "You read supplier receipts and invoices for a small shop in Kenya. Transcribe this "
    "receipt into the record_receipt tool exactly as printed: every purchased line with its "
    "name, quantity, unit cost and printed line amount; the supplier, receipt number, date "
    "and totals when visible. Amounts are usually Kenyan shillings. Do not guess, round, "
    "translate product names or add lines that are not on the paper. If the image is not a "
    "receipt or is unreadable, return zero lines."
)


class AnthropicReceiptExtractionProvider:
    """image → ReceiptExtraction through a forced tool call; no business context is sent."""

    name = "anthropic"

    def __init__(self, settings: Settings) -> None:
        if settings.anthropic_api_key is None:
            msg = "ANTHROPIC_API_KEY is not configured"
            raise ValueError(msg)
        self._client = anthropic.AsyncAnthropic(
            api_key=settings.anthropic_api_key.get_secret_value(),
            timeout=settings.ai_request_timeout_seconds,
            max_retries=1,
        )
        self._model = settings.ai_model

    async def extract(self, image: bytes, *, mime_type: str) -> ExtractionResult:
        params: dict[str, Any] = {
            "model": self._model,
            "max_tokens": RECEIPT_MODEL_MAX_TOKENS,
            "tools": [RECEIPT_TOOL],
            "tool_choice": {"type": "tool", "name": "record_receipt"},
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": mime_type,
                                "data": base64.b64encode(image).decode("ascii"),
                            },
                        },
                        {"type": "text", "text": RECEIPT_PROMPT},
                    ],
                }
            ],
        }
        try:
            message = await self._client.messages.create(**params)
        except anthropic.APITimeoutError:
            logger.warning("receipt provider timeout", extra={"ai_model": self._model})
            raise AIUnavailableError(
                "Reading the receipt took too long. Please try again.", code="AI_TIMEOUT"
            ) from None
        except anthropic.RateLimitError:
            raise AIUnavailableError(
                "The receipt reader is busy right now. Please try again in a moment.",
                code="AI_PROVIDER_BUSY",
                headers={"Retry-After": "30"},
            ) from None
        except anthropic.APIConnectionError:
            logger.warning("receipt provider unreachable", extra={"ai_model": self._model})
            raise AIUnavailableError(
                "The receipt reader is unavailable right now. Please try again."
            ) from None
        except anthropic.APIStatusError as exc:
            body = exc.body if isinstance(exc.body, dict) else {}
            err = body.get("error", {}) if isinstance(body, dict) else {}
            logger.error(
                "receipt provider error",
                extra={
                    "ai_model": self._model,
                    "provider_status": exc.status_code,
                    "provider_error_type": err.get("type") if isinstance(err, dict) else None,
                    "provider_message": str(err.get("message", ""))[:200]
                    if isinstance(err, dict)
                    else None,
                },
            )
            raise AIUnavailableError(
                "The receipt reader is unavailable right now. Please try again."
            ) from None
        return parse_tool_result(message, provider=self.name)


def parse_tool_result(message: anthropic.types.Message, *, provider: str) -> ExtractionResult:
    """Take the forced tool call's input and validate it strictly; anything else is a failure."""
    for block in message.content:
        if (
            getattr(block, "type", None) == "tool_use"
            and getattr(block, "name", "") == "record_receipt"
        ):
            raw = getattr(block, "input", None)
            try:
                extraction = ReceiptExtraction.model_validate(raw)
            except ValidationError as exc:
                logger.error(
                    "receipt extraction failed validation", extra={"errors": exc.error_count()}
                )
                raise ReceiptExtractionError(
                    "The receipt could not be read reliably. Try a clearer photo."
                ) from None
            return ExtractionResult(extraction=extraction, provider=provider, model=message.model)
    logger.error("receipt extraction returned no tool call")
    raise ReceiptExtractionError("The receipt could not be read reliably. Try a clearer photo.")


def build_receipt_provider(settings: Settings) -> ReceiptExtractionProvider | None:
    return AnthropicReceiptExtractionProvider(settings) if settings.anthropic_api_key else None
