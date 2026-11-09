"""Integration tests for the circulation service + endpoints.

Uses the real app with FakePeaceCoin so send-flow validation + outbox
insertion exercise all the service branches.
"""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import falcon.util
from falcon import testing
from sqlalchemy import select

from iconomy.circulation.models import CirculationEvent, Sentiment
from iconomy.core.db import Database
from iconomy.indexer.models import OnchainIntent, OnchainIntentKind, OnchainIntentStatus

if TYPE_CHECKING:
    from iconomy.peacecoin.fake import FakePeaceCoin


def _wallet_of(db: Database, email: str) -> tuple[str, str]:
    """Return (user_id, wallet_address) for the member with this email."""
    from iconomy.accounts.models import User

    async def q() -> tuple[str, str]:
        async with db.session() as session:
            user = (await session.execute(select(User).where(User.email == email))).scalar_one()
            assert user.wallet_address is not None
            return str(user.id), user.wallet_address

    return falcon.util.async_to_sync(q)


def _signed_in(
    client: testing.TestClient, as_member: Callable[..., dict[str, str]], **tok: object
) -> dict[str, str]:
    # Trigger provisioning so the member exists and has a wallet.
    headers = as_member(**tok)
    assert client.simulate_get("/auth/me", headers=headers).status_code == 200
    return headers


def _choose_role(client: testing.TestClient, headers: dict[str, str], role: str) -> None:
    r = client.simulate_post("/auth/me/role", headers=headers, body=f'{{"role":"{role}"}}')
    assert r.status_code in (200, 409), r.json  # already-chosen is fine for repeat runs


DEFAULT_MESSAGE = "mensagem longa o bastante"


def _send_body(to_member_id: str, *, amount: int = 1, message: str = DEFAULT_MESSAGE) -> str:
    import json

    return json.dumps({"toMemberId": to_member_id, "amount": amount, "message": message})


def test_send_rejects_short_message(
    client: testing.TestClient, as_member: Callable[..., dict[str, str]], database: Database
) -> None:
    headers = _signed_in(client, as_member, subject="sender", email="sender@example.org")
    _choose_role(client, headers, "student")
    _signed_in(client, as_member, subject="recipient", email="recipient@example.org")
    recipient_id, _ = _wallet_of(database, "recipient@example.org")

    r = client.simulate_post(
        "/circulation/send",
        headers=headers,
        body=_send_body(recipient_id, message="curta"),
    )
    assert r.status_code == 422
    assert r.json["code"] == "validation_error"


def test_send_rejects_self_transfer(
    client: testing.TestClient, as_member: Callable[..., dict[str, str]], database: Database
) -> None:
    headers = _signed_in(client, as_member, subject="selfer", email="self@example.org")
    _choose_role(client, headers, "student")
    me_id, _ = _wallet_of(database, "self@example.org")

    r = client.simulate_post(
        "/circulation/send",
        headers=headers,
        body=_send_body(me_id),
    )
    assert r.status_code == 422
    assert "yourself" in r.json["detail"].lower()


def test_send_rejects_insufficient_balance(
    client: testing.TestClient, as_member: Callable[..., dict[str, str]], database: Database
) -> None:
    # Fresh members start with 0 UAIFAI (FakePeaceCoin).
    headers = _signed_in(client, as_member, subject="poor", email="poor@example.org")
    _choose_role(client, headers, "student")
    _signed_in(client, as_member, subject="dest", email="dest@example.org")
    recipient_id, _ = _wallet_of(database, "dest@example.org")

    r = client.simulate_post(
        "/circulation/send",
        headers=headers,
        body=_send_body(recipient_id),
    )
    assert r.status_code == 422
    assert "balance" in r.json["detail"].lower()


def test_send_rejects_unknown_recipient(
    client: testing.TestClient, as_member: Callable[..., dict[str, str]]
) -> None:
    headers = _signed_in(client, as_member, subject="s1", email="s1@example.org")
    _choose_role(client, headers, "student")

    r = client.simulate_post(
        "/circulation/send",
        headers=headers,
        body=_send_body("00000000-0000-0000-0000-000000000000"),
    )
    assert r.status_code == 404


def test_send_without_role_is_forbidden(
    client: testing.TestClient, as_member: Callable[..., dict[str, str]], database: Database
) -> None:
    headers = _signed_in(client, as_member, subject="noro", email="noro@example.org")
    _signed_in(client, as_member, subject="dest2", email="dest2@example.org")
    recipient_id, _ = _wallet_of(database, "dest2@example.org")

    r = client.simulate_post(
        "/circulation/send",
        headers=headers,
        body=_send_body(recipient_id),
    )
    assert r.status_code == 403


def test_send_persists_intent_and_returns_202(
    client: testing.TestClient,
    as_member: Callable[..., dict[str, str]],
    database: Database,
    peacecoin: "FakePeaceCoin",
) -> None:
    headers = _signed_in(client, as_member, subject="rich", email="rich@example.org")
    _choose_role(client, headers, "student")
    _signed_in(client, as_member, subject="dest3", email="dest3@example.org")
    sender_id, sender_wallet = _wallet_of(database, "rich@example.org")
    recipient_id, _ = _wallet_of(database, "dest3@example.org")

    peacecoin.credit(sender_wallet, 100 * 10**18)

    r = client.simulate_post(
        "/circulation/send",
        headers=headers,
        body=_send_body(recipient_id, amount=10, message="Obrigada pela facilitação!"),
    )
    assert r.status_code == 202, r.json
    assert r.json["status"] == "pending"

    # Intent landed in the outbox with the right payload.
    async def read_intent() -> OnchainIntent:
        async with database.session() as session:
            return (
                await session.execute(
                    select(OnchainIntent).where(OnchainIntent.id == r.json["intentId"])
                )
            ).scalar_one()

    intent = falcon.util.async_to_sync(read_intent)
    assert intent.kind == OnchainIntentKind.SEND_WITH_MESSAGE
    assert intent.status == OnchainIntentStatus.PENDING
    assert intent.payload["amount_wei"] == str(10 * 10**18)
    assert intent.payload["sender_user_id"] == sender_id
    assert intent.payload["sentiment"] == Sentiment.POSITIVE.value


def _seed_event(
    db: Database,
    *,
    sender_user_id: object,
    recipient_user_id: object,
    sender_address: str,
    recipient_address: str,
    amount: int,
    occurred_at: datetime,
    message: str = "Obrigada pela facilitação!",
    sentiment: Sentiment = Sentiment.POSITIVE,
    tx_hash: str | None = None,
) -> None:
    async def seed() -> None:
        async with db.session() as session:
            session.add(
                CirculationEvent(
                    tx_hash=tx_hash or f"0x{occurred_at.timestamp():.0f}".ljust(66, "0"),
                    block_number=1,
                    log_index=0,
                    sender_address=sender_address,
                    recipient_address=recipient_address,
                    sender_user_id=sender_user_id,
                    recipient_user_id=recipient_user_id,
                    amount=amount,
                    bonus=amount // 10,
                    message=message,
                    sentiment=sentiment.value,
                    occurred_at=occurred_at,
                )
            )

    falcon.util.async_to_sync(seed)


def test_feed_returns_events_newest_first(
    client: testing.TestClient, as_member: Callable[..., dict[str, str]], database: Database
) -> None:
    headers = _signed_in(client, as_member, subject="a", email="a@example.org")
    _signed_in(client, as_member, subject="b", email="b@example.org")
    a_id, a_wallet = _wallet_of(database, "a@example.org")
    b_id, b_wallet = _wallet_of(database, "b@example.org")

    older = datetime(2026, 10, 10, tzinfo=UTC)
    newer = datetime(2026, 10, 17, tzinfo=UTC)
    _seed_event(
        database,
        sender_user_id=a_id,
        recipient_user_id=b_id,
        sender_address=a_wallet,
        recipient_address=b_wallet,
        amount=50 * 10**18,
        occurred_at=older,
    )
    _seed_event(
        database,
        sender_user_id=b_id,
        recipient_user_id=a_id,
        sender_address=b_wallet,
        recipient_address=a_wallet,
        amount=20 * 10**18,
        occurred_at=newer,
    )

    r = client.simulate_get("/circulation", headers=headers)
    assert r.status_code == 200, r.json
    assert len(r.json) == 2
    assert r.json[0]["amount"] == 20  # newest first
    assert r.json[0]["senderName"]  # names resolved via JOIN
    assert r.json[1]["amount"] == 50


def test_transactions_classifies_sent_and_received(
    client: testing.TestClient, as_member: Callable[..., dict[str, str]], database: Database
) -> None:
    headers = _signed_in(client, as_member, subject="viewer", email="viewer@example.org")
    _signed_in(client, as_member, subject="other", email="other@example.org")
    viewer_id, viewer_wallet = _wallet_of(database, "viewer@example.org")
    other_id, other_wallet = _wallet_of(database, "other@example.org")

    _seed_event(
        database,
        sender_user_id=viewer_id,
        recipient_user_id=other_id,
        sender_address=viewer_wallet,
        recipient_address=other_wallet,
        amount=5 * 10**18,
        occurred_at=datetime(2026, 10, 17, tzinfo=UTC),
    )
    _seed_event(
        database,
        sender_user_id=other_id,
        recipient_user_id=viewer_id,
        sender_address=other_wallet,
        recipient_address=viewer_wallet,
        amount=3 * 10**18,
        occurred_at=datetime(2026, 10, 16, tzinfo=UTC),
    )

    r = client.simulate_get("/circulation/transactions", headers=headers)
    assert r.status_code == 200
    kinds = [t["kind"] for t in r.json]
    assert kinds == ["sent", "received"]


def test_feed_without_token_is_401(client: testing.TestClient) -> None:
    assert client.simulate_get("/circulation").status_code == 401


def test_feed_filters_by_sentiment(
    client: testing.TestClient, as_member: Callable[..., dict[str, str]], database: Database
) -> None:
    headers = _signed_in(client, as_member, subject="viewer2", email="viewer2@example.org")
    _signed_in(client, as_member, subject="other2", email="other2@example.org")
    viewer_id, viewer_wallet = _wallet_of(database, "viewer2@example.org")
    other_id, other_wallet = _wallet_of(database, "other2@example.org")

    _seed_event(
        database,
        sender_user_id=viewer_id,
        recipient_user_id=other_id,
        sender_address=viewer_wallet,
        recipient_address=other_wallet,
        amount=1 * 10**18,
        occurred_at=datetime(2026, 10, 17, tzinfo=UTC),
        sentiment=Sentiment.POSITIVE,
        tx_hash="0x" + "a" * 64,
    )
    _seed_event(
        database,
        sender_user_id=viewer_id,
        recipient_user_id=other_id,
        sender_address=viewer_wallet,
        recipient_address=other_wallet,
        amount=2 * 10**18,
        occurred_at=datetime(2026, 10, 16, tzinfo=UTC),
        sentiment=Sentiment.NEUTRAL,
        tx_hash="0x" + "b" * 64,
    )

    r = client.simulate_get("/circulation?sentiment=1", headers=headers)
    assert r.status_code == 200
    assert len(r.json) == 1
    assert r.json[0]["sentiment"] == 1


def test_circulation_30d_counts_only_recent_sends(database: Database) -> None:
    from iconomy.circulation.repository import CirculationRepository

    sender_wallet = "0x" + "1" * 40
    recipient_wallet = "0x" + "2" * 40

    _seed_event(
        database,
        sender_user_id=None,
        recipient_user_id=None,
        sender_address=sender_wallet,
        recipient_address=recipient_wallet,
        amount=100 * 10**18,
        occurred_at=datetime.now(UTC) - timedelta(days=5),
        tx_hash="0x" + "c" * 64,
    )
    _seed_event(
        database,
        sender_user_id=None,
        recipient_user_id=None,
        sender_address=sender_wallet,
        recipient_address=recipient_wallet,
        amount=999 * 10**18,
        occurred_at=datetime.now(UTC) - timedelta(days=40),  # outside window
        tx_hash="0x" + "d" * 64,
    )

    async def total() -> int:
        async with database.session() as session:
            return await CirculationRepository(session).circulation_30d(sender_wallet)

    assert falcon.util.async_to_sync(total) == 100 * 10**18


# --- Intent status polling (pending -> confirmed) ---------------------------


def test_intent_status_follows_the_senders_own_intent(
    client: testing.TestClient,
    as_member: Callable[..., dict[str, str]],
    database: Database,
    peacecoin: "FakePeaceCoin",
) -> None:
    headers = _signed_in(client, as_member, subject="poller", email="poller@example.org")
    _choose_role(client, headers, "student")
    _signed_in(client, as_member, subject="pollee", email="pollee@example.org")
    _, sender_wallet = _wallet_of(database, "poller@example.org")
    recipient_id, _ = _wallet_of(database, "pollee@example.org")
    peacecoin.credit(sender_wallet, 100 * 10**18)

    sent = client.simulate_post(
        "/circulation/send",
        headers=headers,
        body=_send_body(recipient_id, amount=5, message="mensagem longa o bastante"),
    )
    intent_id = sent.json["intentId"]

    status = client.simulate_get(f"/circulation/intents/{intent_id}", headers=headers)
    assert status.status_code == 200, status.json
    assert status.json["intentId"] == intent_id
    assert status.json["status"] == "pending"
    assert status.json["txHash"] is None
    # A pending intent has no failure to report yet.
    assert status.json["failureReason"] is None


def test_intent_status_hides_another_members_intent(
    client: testing.TestClient,
    as_member: Callable[..., dict[str, str]],
    database: Database,
    peacecoin: "FakePeaceCoin",
) -> None:
    owner = _signed_in(client, as_member, subject="owner", email="owner@example.org")
    _choose_role(client, owner, "student")
    _signed_in(client, as_member, subject="target", email="target@example.org")
    _, owner_wallet = _wallet_of(database, "owner@example.org")
    target_id, _ = _wallet_of(database, "target@example.org")
    peacecoin.credit(owner_wallet, 100 * 10**18)

    intent_id = client.simulate_post(
        "/circulation/send",
        headers=owner,
        body=_send_body(target_id, amount=1, message="mensagem longa o bastante"),
    ).json["intentId"]

    # A different member must not learn anything about it.
    intruder = _signed_in(client, as_member, subject="intruder", email="intruder@example.org")
    assert (
        client.simulate_get(f"/circulation/intents/{intent_id}", headers=intruder).status_code
        == 404
    )


def test_intent_status_rejects_a_malformed_id(
    client: testing.TestClient, as_member: Callable[..., dict[str, str]]
) -> None:
    headers = _signed_in(client, as_member, subject="badid", email="badid@example.org")
    assert (
        client.simulate_get("/circulation/intents/not-a-uuid", headers=headers).status_code == 422
    )


def test_intent_status_requires_a_token(client: testing.TestClient) -> None:
    assert (
        client.simulate_get("/circulation/intents/11111111-1111-1111-1111-111111111111").status_code
        == 401
    )
