from collections.abc import Callable

from falcon import testing


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
