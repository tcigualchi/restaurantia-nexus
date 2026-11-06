"""Test helpers shared by integration and security suites."""

from __future__ import annotations


def demo_login(client, persona: str = "manager", ip: str | None = None) -> tuple[dict[str, str], list[dict]]:
    headers = {"X-Forwarded-For": ip} if ip else {}
    resp = client.post("/api/v1/auth/demo", json={"persona": persona}, headers=headers)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    return {"Authorization": f"Bearer {body['access_token']}"}, body["restaurants"]
