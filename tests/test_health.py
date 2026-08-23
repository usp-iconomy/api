from falcon import testing


def test_liveness_responds_without_dependencies(client: testing.TestClient) -> None:
    result = client.simulate_get("/health/live")

    assert result.status_code == 200
    assert result.json == {"status": "alive"}


def test_every_response_carries_a_request_id(client: testing.TestClient) -> None:
    result = client.simulate_get("/health/live")

    assert result.headers["X-Request-ID"]


def test_client_supplied_request_id_is_preserved(client: testing.TestClient) -> None:
    result = client.simulate_get("/health/live", headers={"X-Request-ID": "abc-123"})

    assert result.headers["X-Request-ID"] == "abc-123"


def test_unknown_route_returns_problem_json(client: testing.TestClient) -> None:
    result = client.simulate_get("/unknown-route")

    assert result.status_code == 404
    assert result.json["code"] == "http_404"
    assert result.json["status"] == 404
