from datetime import timedelta

from cryptography.hazmat.primitives.asymmetric import rsa
from falcon import testing


def test_current_user_requires_a_token(client: testing.TestClient) -> None:
    result = client.simulate_get("/auth/me")

    assert result.status_code == 401
    assert result.json["code"] == "unauthorized"


def test_only_the_bearer_scheme_is_accepted(client: testing.TestClient) -> None:
    result = client.simulate_get("/auth/me", headers={"Authorization": "Basic abc"})

    assert result.status_code == 401


def test_a_token_signed_by_an_unknown_key_is_refused(
    client: testing.TestClient, issue_token
) -> None:
    intruder = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    result = client.simulate_get(
        "/auth/me",
        headers={"Authorization": f"Bearer {issue_token(key=intruder)}"},
    )

    assert result.status_code == 401


def test_a_token_naming_an_unknown_key_id_is_refused(
    client: testing.TestClient, issue_token
) -> None:
    result = client.simulate_get(
        "/auth/me", headers={"Authorization": f"Bearer {issue_token(kid='rotated-away')}"}
    )

    assert result.status_code == 401


def test_an_expired_token_is_refused(client: testing.TestClient, as_member) -> None:
    result = client.simulate_get("/auth/me", headers=as_member(expires_in=timedelta(minutes=-5)))

    assert result.status_code == 401


def test_a_token_for_another_audience_is_refused(client: testing.TestClient, as_member) -> None:
    result = client.simulate_get("/auth/me", headers=as_member(aud="another-api"))

    assert result.status_code == 401


def test_a_token_from_another_issuer_is_refused(client: testing.TestClient, as_member) -> None:
    result = client.simulate_get(
        "/auth/me", headers=as_member(iss="https://elsewhere.test/realms/iconomy")
    )

    assert result.status_code == 401


def test_a_token_without_an_email_claim_is_refused(client: testing.TestClient, as_member) -> None:
    result = client.simulate_get("/auth/me", headers=as_member(email=None))

    assert result.status_code == 401


def test_a_garbled_token_is_refused(client: testing.TestClient) -> None:
    result = client.simulate_get("/auth/me", headers={"Authorization": "Bearer not.a.jwt"})

    assert result.status_code == 401


def test_the_first_call_provisions_the_member(client: testing.TestClient, as_member) -> None:
    result = client.simulate_get("/auth/me", headers=as_member(email="joel@example.org"))

    assert result.status_code == 200
    assert result.json["user"]["email"] == "joel@example.org"
    assert result.json["user"]["role"] is None
    assert result.json["onboardingRequired"] is True


def test_the_wire_format_is_camel_case(client: testing.TestClient, as_member) -> None:
    result = client.simulate_get("/auth/me", headers=as_member())

    assert "onboardingRequired" in result.json
    assert "emailVerified" in result.json
    assert "isInstitutional" in result.json["user"]
    assert "createdAt" in result.json["user"]


def test_a_usp_address_is_recorded_as_institutional(client: testing.TestClient, as_member) -> None:
    result = client.simulate_get("/auth/me", headers=as_member(email="ana@usp.br"))

    assert result.json["user"]["isInstitutional"] is True


def test_a_usp_subdomain_is_recorded_as_institutional(
    client: testing.TestClient, as_member
) -> None:
    result = client.simulate_get("/auth/me", headers=as_member(email="ana@ime.usp.br"))

    assert result.json["user"]["isInstitutional"] is True


def test_an_address_merely_ending_in_usp_br_is_not_institutional(
    client: testing.TestClient, as_member
) -> None:
    result = client.simulate_get("/auth/me", headers=as_member(email="golpe@naousp.br"))

    assert result.json["user"]["isInstitutional"] is False


def test_an_external_address_is_not_institutional(client: testing.TestClient, as_member) -> None:
    result = client.simulate_get("/auth/me", headers=as_member(email="joel@example.org"))

    assert result.json["user"]["isInstitutional"] is False


def test_a_subject_is_provisioned_only_once(client: testing.TestClient, as_member) -> None:
    headers = as_member(subject="stable-subject")

    first = client.simulate_get("/auth/me", headers=headers)
    second = client.simulate_get("/auth/me", headers=headers)

    assert first.json["user"]["id"] == second.json["user"]["id"]


def test_identity_changes_are_mirrored_locally(client: testing.TestClient, as_member) -> None:
    client.simulate_get(
        "/auth/me", headers=as_member(subject="s-1", email="antes@usp.br", name="Antes")
    )

    result = client.simulate_get(
        "/auth/me",
        headers=as_member(subject="s-1", email="depois@example.org", name="Depois"),
    )

    assert result.json["user"]["email"] == "depois@example.org"
    assert result.json["user"]["name"] == "Depois"
    assert result.json["user"]["isInstitutional"] is False


def test_two_subjects_cannot_share_an_email(client: testing.TestClient, as_member) -> None:
    client.simulate_get("/auth/me", headers=as_member(subject="s-1", email="dupla@example.org"))

    result = client.simulate_get(
        "/auth/me", headers=as_member(subject="s-2", email="dupla@example.org")
    )

    assert result.status_code == 409


def test_choosing_a_role_completes_onboarding(client: testing.TestClient, as_member) -> None:
    headers = as_member(subject="s-role")

    chosen = client.simulate_post("/auth/me/role", headers=headers, json={"role": "teacher"})
    profile = client.simulate_get("/auth/me", headers=headers)

    assert chosen.status_code == 200
    assert chosen.json["role"] == "teacher"
    assert profile.json["onboardingRequired"] is False


def test_a_role_cannot_be_chosen_twice(client: testing.TestClient, as_member) -> None:
    headers = as_member(subject="s-twice")
    client.simulate_post("/auth/me/role", headers=headers, json={"role": "student"})

    result = client.simulate_post("/auth/me/role", headers=headers, json={"role": "teacher"})

    assert result.status_code == 409
    assert result.json["context"] == {"role": "student"}


def test_admin_cannot_be_self_assigned(client: testing.TestClient, as_member) -> None:
    result = client.simulate_post("/auth/me/role", headers=as_member(), json={"role": "admin"})

    assert result.status_code == 422


def test_an_unknown_role_is_refused(client: testing.TestClient, as_member) -> None:
    result = client.simulate_post("/auth/me/role", headers=as_member(), json={"role": "reitor"})

    assert result.status_code == 422


def test_choosing_a_role_requires_a_token(client: testing.TestClient) -> None:
    result = client.simulate_post("/auth/me/role", json={"role": "student"})

    assert result.status_code == 401


def test_an_empty_body_is_refused(client: testing.TestClient, as_member) -> None:
    result = client.simulate_post("/auth/me/role", headers=as_member())

    assert result.status_code == 422
