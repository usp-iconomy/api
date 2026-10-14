from collections.abc import Callable

from falcon import testing


def _auth_me(client: testing.TestClient, headers: dict[str, str]) -> dict[str, object]:
    result = client.simulate_get("/auth/me", headers=headers)
    assert result.status_code == 200, result.json
    return result.json


def test_sign_in_provisions_wallet_address(
    client: testing.TestClient, as_member: Callable[..., dict[str, str]]
) -> None:
    headers = as_member()

    body = _auth_me(client, headers)
    user = body["user"]

    assert isinstance(user["walletAddress"], str)
    assert user["walletAddress"].startswith("0x")
    assert len(user["walletAddress"]) == 42


def test_wallet_address_is_stable_across_sign_ins(
    client: testing.TestClient, as_member: Callable[..., dict[str, str]]
) -> None:
    headers = as_member(subject="stable-subject")

    first = _auth_me(client, headers)["user"]
    second = _auth_me(client, headers)["user"]

    assert first["walletAddress"] == second["walletAddress"]


def test_new_members_start_with_empty_profile_lists(
    client: testing.TestClient, as_member: Callable[..., dict[str, str]]
) -> None:
    body = _auth_me(client, as_member())
    user = body["user"]

    assert user["community"] is None
    assert user["skillsOffered"] == []
    assert user["skillsWanted"] == []
