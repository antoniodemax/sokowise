"""Match extracted receipt lines to the business's own catalogue (docs/ARCHITECTURE.md §6.7).

The model never sees product ids. Matching is conservative: an exact normalised name,
SKU or barcode is MATCHED; a close but not certain name gives AMBIGUOUS with a short
candidate list for the owner to choose from; anything else is UNMATCHED.
"""

import re
import uuid
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from app.models import Product
from app.models.enums import ReceiptMatchStatus

MATCH_THRESHOLD = 0.90  # unique best score at or above this → MATCHED
CANDIDATE_THRESHOLD = 0.70  # scores at or above this are offered as candidates
MAX_CANDIDATES = 3
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def normalise(text: str) -> str:
    return " ".join(_NON_ALNUM.sub(" ", text.lower()).split())


@dataclass(frozen=True, slots=True)
class MatchResult:
    status: ReceiptMatchStatus
    product_id: uuid.UUID | None = None
    candidates: list[uuid.UUID] = field(default_factory=list)


def match_line(name: str, sku: str | None, products: list[Product]) -> MatchResult:
    wanted = normalise(name)
    wanted_sku = sku.strip().lower() if sku else None
    if wanted_sku:
        for product in products:
            if (product.sku and product.sku.lower() == wanted_sku) or (
                product.barcode and product.barcode.lower() == wanted_sku
            ):
                return MatchResult(ReceiptMatchStatus.MATCHED, product.id)
    exact = [p for p in products if normalise(p.name) == wanted]
    if len(exact) == 1:
        return MatchResult(ReceiptMatchStatus.MATCHED, exact[0].id)
    if len(exact) > 1:
        return MatchResult(
            ReceiptMatchStatus.AMBIGUOUS, None, [p.id for p in exact[:MAX_CANDIDATES]]
        )
    if not wanted:
        return MatchResult(ReceiptMatchStatus.UNMATCHED)
    scored = sorted(
        ((SequenceMatcher(None, wanted, normalise(p.name)).ratio(), p) for p in products),
        key=lambda item: item[0],
        reverse=True,
    )
    candidates = [p for score, p in scored if score >= CANDIDATE_THRESHOLD][:MAX_CANDIDATES]
    if not candidates:
        return MatchResult(ReceiptMatchStatus.UNMATCHED)
    best_score = scored[0][0]
    runner_up = scored[1][0] if len(scored) > 1 else 0.0
    if best_score >= MATCH_THRESHOLD and runner_up < MATCH_THRESHOLD:
        return MatchResult(ReceiptMatchStatus.MATCHED, candidates[0].id, [p.id for p in candidates])
    return MatchResult(ReceiptMatchStatus.AMBIGUOUS, None, [p.id for p in candidates])
