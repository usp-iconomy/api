import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from iconomy.circulation.models import Sentiment
from iconomy.circulation.schemas import (
    CirculationEntryResponse,
    SendRequest,
    SendResponse,
    TransactionKind,
    TransactionResponse,
    TransactionStatus,
)


class TestSendRequest:
    def test_accepts_valid_payload(self) -> None:
        req = SendRequest.model_validate(
            {
                "toMemberId": "11111111-1111-1111-1111-111111111111",
                "amount": 50,
                "message": "Obrigada pela facilitação!",
            }
        )
        assert req.amount == 50
        assert str(req.to_member_id) == "11111111-1111-1111-1111-111111111111"

    def test_message_strips_whitespace(self) -> None:
        req = SendRequest.model_validate(
            {
                "toMemberId": "11111111-1111-1111-1111-111111111111",
                "amount": 1,
                "message": "   dez chars.   ",
            }
        )
        assert req.message == "dez chars."

    def test_rejects_short_message(self) -> None:
        with pytest.raises(ValidationError, match="at least 10 characters"):
            SendRequest.model_validate(
                {
                    "toMemberId": "11111111-1111-1111-1111-111111111111",
                    "amount": 1,
                    "message": "pequena",
                }
            )

    def test_rejects_whitespace_only_message(self) -> None:
        with pytest.raises(ValidationError, match="at least 10 characters"):
            SendRequest.model_validate(
                {
                    "toMemberId": "11111111-1111-1111-1111-111111111111",
                    "amount": 1,
                    "message": "          ",
                }
            )

    def test_rejects_non_positive_amount(self) -> None:
        with pytest.raises(ValidationError):
            SendRequest.model_validate(
                {
                    "toMemberId": "11111111-1111-1111-1111-111111111111",
                    "amount": 0,
                    "message": "mensagem longa o suficiente",
                }
            )


class TestSendResponse:
    def test_wire_shape_is_camel_case(self) -> None:
        intent = uuid.uuid4()
        payload = SendResponse(intent_id=intent).to_media()
        assert payload == {"intentId": str(intent), "status": "pending"}


class TestCirculationEntryResponse:
    def test_wire_shape_matches_front_contract(self) -> None:
        entry_id = uuid.uuid4()
        occurred = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)
        media = CirculationEntryResponse(
            id=entry_id,
            sender_name="Maria",
            recipient_name="João",
            amount=50,
            message="Obrigada pela facilitação!",
            occurred_at=occurred,
            sentiment=Sentiment.POSITIVE,
        ).to_media()
        assert media == {
            "id": str(entry_id),
            "senderName": "Maria",
            "recipientName": "João",
            "amount": 50,
            "message": "Obrigada pela facilitação!",
            "occurredAt": "2026-10-18T12:00:00Z",
            "sentiment": 1,
            "courseTitle": None,
        }


class TestTransactionResponse:
    def test_wire_shape_matches_front_contract(self) -> None:
        tx_id = uuid.uuid4()
        occurred = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)
        media = TransactionResponse(
            id=tx_id,
            kind=TransactionKind.SENT,
            description="Enviou 50 UAIFAI para João",
            amount=50,
            occurred_at=occurred,
            status=TransactionStatus.COMPLETED,
        ).to_media()
        assert media == {
            "id": str(tx_id),
            "kind": "sent",
            "description": "Enviou 50 UAIFAI para João",
            "amount": 50,
            "occurredAt": "2026-10-18T12:00:00Z",
            "status": "completed",
        }

    def test_sbt_issuance_has_null_amount(self) -> None:
        media = TransactionResponse(
            id=uuid.uuid4(),
            kind=TransactionKind.SBT_ISSUED,
            description="Token Alma: Educação Comunitária",
            amount=None,
            occurred_at=datetime(2026, 10, 18, tzinfo=UTC),
            status=TransactionStatus.ISSUED,
        ).to_media()
        assert media["amount"] is None
        assert media["status"] == "issued"
