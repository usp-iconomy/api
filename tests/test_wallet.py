from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import falcon.util
from falcon import testing
from sqlalchemy import select

from iconomy.accounts.models import User
from iconomy.circulation.models import CirculationEvent, Sentiment
from iconomy.core.db import Database


def test_wallet_me_requires_a_token(client: testing.TestClient) -> None:
    result = client.simulate_get("/wallet/me")

    assert result.status_code == 401


def test_wallet_me_returns_summary_shape(
    client: testing.TestClient, as_member: Callable[..., dict[str, str]]
) -> None:
    result = client.simulate_get("/wallet/me", headers=as_member())

    assert result.status_code == 200, result.json
    body = result.json
    assert set(body.keys()) == {
        "tokenBalance",
        "circulationCount",
        "soulTokenCount",
        "reputationStars",
        "reputationLabel",
    }


def test_fresh_member_sees_zero_balance_and_lowest_tier(
    client: testing.TestClient, as_member: Callable[..., dict[str, str]]
) -> None:
    body = client.simulate_get("/wallet/me", headers=as_member()).json

    # FakePeaceCoin returns 0 for a freshly minted address.
    assert body["tokenBalance"] == 0
    assert body["circulationCount"] == 0
    assert body["soulTokenCount"] == 0
    assert body["reputationStars"] == 1
    assert body["reputationLabel"] == "Recém-chegada"


def test_circulation_count_sums_sent_amount_in_last_30_days(
    client: testing.TestClient,
    as_member: Callable[..., dict[str, str]],
    database: Database,
) -> None:
    """Seed two events for the signed-in user: one recent (counts) and one
    40 days old (ignored). `circulationCount` should sum only the recent one.
    """
    headers = as_member(subject="circ-user", email="circ@example.org")
    # Trigger provisioning so the wallet exists.
    assert client.simulate_get("/wallet/me", headers=headers).status_code == 200

    async def seed_events_for_signed_in_user() -> None:
        async with database.session() as session:
            user = (
                await session.execute(select(User).where(User.email == "circ@example.org"))
            ).scalar_one()
            assert user.wallet_address is not None
            session.add_all(
                [
                    CirculationEvent(
                        tx_hash="0x" + "1" * 64,
                        block_number=1,
                        log_index=0,
                        sender_address=user.wallet_address,
                        recipient_address="0x" + "2" * 40,
                        sender_user_id=user.id,
                        recipient_user_id=None,
                        amount=50 * 10**18,  # counts
                        bonus=5 * 10**18,
                        message="mensagem longa o bastante",
                        sentiment=Sentiment.NEUTRAL.value,
                        occurred_at=datetime.now(UTC) - timedelta(days=5),
                    ),
                    CirculationEvent(
                        tx_hash="0x" + "2" * 64,
                        block_number=1,
                        log_index=0,
                        sender_address=user.wallet_address,
                        recipient_address="0x" + "2" * 40,
                        sender_user_id=user.id,
                        recipient_user_id=None,
                        amount=999 * 10**18,  # outside window
                        bonus=0,
                        message="mensagem longa o bastante",
                        sentiment=Sentiment.NEUTRAL.value,
                        occurred_at=datetime.now(UTC) - timedelta(days=40),
                    ),
                ]
            )

    falcon.util.async_to_sync(seed_events_for_signed_in_user)

    body = client.simulate_get("/wallet/me", headers=headers).json
    # Only the 50-UAIFAI event in the last 30 days should count.
    assert body["circulationCount"] == 50
