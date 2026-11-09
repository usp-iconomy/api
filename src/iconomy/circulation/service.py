"""Orchestration of circulation reads and writes.

Writes land in the outbox (`onchain_intents`) — the worker drains it and
submits to the chain. Reads come from the read-model materialised by the
indexer. Both are the Fase B shape of the D4/D5 split.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from iconomy.accounts.models import User
from iconomy.circulation.models import Sentiment
from iconomy.circulation.repository import (
    CirculationRepository,
    EnrichedCirculationEvent,
)
from iconomy.circulation.schemas import (
    CirculationEntryResponse,
    IntentStatus,
    IntentStatusResponse,
    SendRequest,
    SendResponse,
    TransactionKind,
    TransactionResponse,
    TransactionStatus,
)
from iconomy.circulation.sentiment import SentimentClassifier
from iconomy.core.db import Database
from iconomy.core.errors import ConflictError, NotFoundError, ValidationError
from iconomy.indexer.models import OnchainIntent, OnchainIntentKind, OnchainIntentStatus
from iconomy.peacecoin.adapter import PeaceCoinAdapter

# UAIFAIToken has 18 decimals (ERC20 default). Users send whole-UAIFAI
# amounts; convert here for the chain payload.
WEI_PER_TOKEN = 10**18


class CirculationService:
    def __init__(
        self,
        database: Database,
        peacecoin: PeaceCoinAdapter,
        sentiment: SentimentClassifier,
    ) -> None:
        self._database = database
        self._peacecoin = peacecoin
        self._sentiment = sentiment

    async def send(self, sender: User, request: SendRequest) -> SendResponse:
        if sender.wallet_address is None:
            raise ConflictError("Your wallet is still being provisioned.")
        if sender.id == request.to_member_id:
            raise ValidationError("You cannot send tokens to yourself.")

        async with self._database.session() as session:
            recipient = await session.get(User, request.to_member_id)
            if recipient is None:
                raise NotFoundError("Recipient not found.")
            if recipient.wallet_address is None:
                raise ConflictError("Recipient's wallet is still being provisioned.")

            # Balance check runs against the chain (Fase A path). Later this
            # can switch to a cached read-model updated by the indexer.
            balance_wei = await self._peacecoin.get_balance(sender.wallet_address)
            amount_wei = request.amount * WEI_PER_TOKEN
            if balance_wei < amount_wei:
                raise ValidationError("Insufficient balance for this transfer.")

            sentiment = await self._sentiment.classify(request.message)

            intent_id = uuid.uuid4()
            session.add(
                OnchainIntent(
                    id=intent_id,
                    kind=OnchainIntentKind.SEND_WITH_MESSAGE,
                    idempotency_key=str(intent_id),
                    status=OnchainIntentStatus.PENDING,
                    payload={
                        "from": sender.wallet_address,
                        "to": recipient.wallet_address,
                        "amount_wei": str(amount_wei),
                        "message": request.message,
                        "sentiment": int(sentiment),
                        "sender_user_id": str(sender.id),
                        "recipient_user_id": str(recipient.id),
                    },
                )
            )

        return SendResponse(intent_id=intent_id)

    async def intent_status(self, user: User, intent_id: uuid.UUID) -> IntentStatusResponse:
        """Status of one of *this member's* intents, so the UI can follow a
        send it just made. Scoped to the caller: the payload records who sent
        it, and another member's intent is reported as not found rather than
        leaking its existence.
        """
        async with self._database.session() as session:
            intent = await session.get(OnchainIntent, intent_id)
            if intent is None or intent.payload.get("sender_user_id") != str(user.id):
                raise NotFoundError("Intent not found.")
            return IntentStatusResponse(
                intent_id=intent.id,
                status=IntentStatus(intent.status.value),
                tx_hash=intent.tx_hash,
                # Only surfaced once we have stopped retrying, so the UI does
                # not alarm the member over a fault that resolves itself.
                failure_reason=(
                    intent.failure_reason if intent.status == OnchainIntentStatus.FAILED else None
                ),
            )

    async def list_feed(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        sentiment: Sentiment | None = None,
        since: datetime | None = None,
    ) -> list[CirculationEntryResponse]:
        async with self._database.session() as session:
            repo = CirculationRepository(session)
            rows = await repo.list_feed(
                limit=limit, offset=offset, sentiment=sentiment, since=since
            )
            return [_to_entry(row) for row in rows]

    async def list_transactions(
        self,
        user: User,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[TransactionResponse]:
        async with self._database.session() as session:
            repo = CirculationRepository(session)
            rows = await repo.list_transactions(user.id, limit=limit, offset=offset)
            return [_to_transaction(row, user) for row in rows]


def _wei_to_tokens(amount_wei: int) -> int:
    """Chain stores wei-like integers; the UI wants whole UAIFAI."""
    return amount_wei // WEI_PER_TOKEN


def _to_entry(row: EnrichedCirculationEvent) -> CirculationEntryResponse:
    event = row.event
    return CirculationEntryResponse(
        id=event.id,
        sender_name=row.sender_name,
        recipient_name=row.recipient_name,
        amount=_wei_to_tokens(event.amount),
        message=event.message,
        occurred_at=event.occurred_at,
        sentiment=Sentiment(event.sentiment),
        course_title=None,  # populated in Fase C once courses enrich events
    )


def _to_transaction(row: EnrichedCirculationEvent, viewer: User) -> TransactionResponse:
    """Classify from the viewer's perspective — sent vs received."""
    event = row.event
    amount_tokens = _wei_to_tokens(event.amount)
    if event.sender_user_id == viewer.id:
        kind = TransactionKind.SENT
        description = f"Enviou {amount_tokens} UAIFAI para {row.recipient_name}"
    else:
        kind = TransactionKind.RECEIVED
        description = f"Recebeu {amount_tokens} UAIFAI de {row.sender_name}"
    return TransactionResponse(
        id=event.id,
        kind=kind,
        description=description,
        amount=amount_tokens,
        occurred_at=event.occurred_at,
        status=TransactionStatus.COMPLETED,
    )
