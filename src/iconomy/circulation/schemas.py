"""Request/response schemas for the circulation module.

Mirrors `CirculationEntry` and `Transaction` from
`front/src/types/domain.ts`. The `Schema` base converts snake_case to
camelCase on the wire via `to_camel`.
"""

import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import Field, field_validator

from iconomy.circulation.models import Sentiment
from iconomy.core.schemas import Schema

MIN_MESSAGE_LENGTH = 10  # RN-02, mirrors UAIFAIToken.MIN_MESSAGE_LENGTH


class TransactionKind(StrEnum):
    SENT = "sent"
    RECEIVED = "received"
    SBT_ISSUED = "sbt_issued"


class TransactionStatus(StrEnum):
    COMPLETED = "completed"
    ISSUED = "issued"
    PENDING = "pending"


class SendRequest(Schema):
    """Body of POST /circulation/send."""

    to_member_id: uuid.UUID
    amount: int = Field(gt=0, description="Whole UAIFAI tokens, not wei-like units.")
    message: str

    @field_validator("message")
    @classmethod
    def _message_long_enough(cls, value: str) -> str:
        stripped = value.strip()
        if len(stripped) < MIN_MESSAGE_LENGTH:
            raise ValueError(f"message must have at least {MIN_MESSAGE_LENGTH} characters")
        return stripped


class SendResponse(Schema):
    """202 Accepted response. The intent is pending until the worker submits it."""

    intent_id: uuid.UUID
    status: TransactionStatus = TransactionStatus.PENDING


class IntentStatus(StrEnum):
    """Lifecycle of an outbox intent, as the UI needs to narrate it."""

    PENDING = "pending"  # queued, worker has not submitted it yet
    SUBMITTED = "submitted"  # on-chain, waiting for the indexer to see it
    CONFIRMED = "confirmed"  # indexed; the feed already shows it
    FAILED = "failed"  # gave up after retries


class IntentStatusResponse(Schema):
    """GET /circulation/intents/{id} — lets the form follow its own send."""

    intent_id: uuid.UUID
    status: IntentStatus
    tx_hash: str | None = None
    failure_reason: str | None = None


class CirculationEntryResponse(Schema):
    """Matches CirculationEntry in front/src/types/domain.ts."""

    id: uuid.UUID
    sender_name: str
    recipient_name: str
    amount: int
    message: str
    occurred_at: datetime
    sentiment: Sentiment
    course_title: str | None = None


class TransactionResponse(Schema):
    """Matches Transaction in front/src/types/domain.ts."""

    id: uuid.UUID
    kind: TransactionKind
    description: str
    amount: int | None
    occurred_at: datetime
    status: TransactionStatus
