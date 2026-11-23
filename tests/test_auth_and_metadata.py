import json
import re

from conftest import ISSUER, RESOURCE_URL, VALID_TOKEN
from fake_dolibarr import User


def _resource_metadata_url(response) -> str:
    m = re.search(r'resource_metadata="([^"]+)"', response.headers["www-authenticate"])
    assert m, response.headers["www-authenticate"]
    return m.group(1)


def _tool_text(response) -> str:
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert result["isError"] is False, result
    return result["content"][0]["text"]


def test_no_token_returns_401_with_resource_metadata_hint(client, dolibarr):
    r = client.post("initialize")

    assert r.status_code == 401
    assert r.headers["www-authenticate"].startswith("Bearer")
    assert _resource_metadata_url(r).startswith("https://mcp.example.test/")
    assert dolibarr.requests == []


def test_token_rejected_by_dolibarr_returns_401(client, dolibarr):
    r = client.call_tool("whoami", token="not-a-valid-token")

    assert r.status_code == 401
    assert "resource_metadata=" in r.headers["www-authenticate"]
    assert [req.path for req in dolibarr.requests] == ["/restoauth/me"]
    assert dolibarr.requests[0].authorization == "Bearer not-a-valid-token"


def test_protected_resource_metadata_points_at_the_restoauth_issuer(client, dolibarr):
    metadata_url = _resource_metadata_url(client.post("initialize"))
    # The advertised URL is the public one; fetch the same path from the test server.
    path = re.sub(r"^https?://[^/]+", "", metadata_url)

    r = client.http.get(client.base_url + path)

    assert r.status_code == 200
    doc = r.json()
    assert doc["resource"] == RESOURCE_URL
    assert [s.rstrip("/") for s in doc["authorization_servers"]] == [ISSUER]


def test_whoami_with_a_valid_token_shows_the_dolibarr_user(client, dolibarr):
    text = _tool_text(client.call_tool("whoami"))

    me = json.loads(text)
    assert me["user"] == "Max Muster (max)"
    assert me["dolibarr"] == "23.0.3"
    assert me["application"] == "Test client"
    # The token goes to Dolibarr unchanged, as a Bearer header and nowhere else.
    assert dolibarr.requests
    for req in dolibarr.requests:
        assert req.authorization == f"Bearer {VALID_TOKEN}"
        assert VALID_TOKEN not in req.query_params.values()


def test_tool_list_offers_all_tools_to_a_user_with_all_read_rights(client, dolibarr):
    assert client.tool_names() == {
        "whoami", "my_permissions", "list_thirdparties", "get_thirdparty", "list_invoices", "get_invoice",
        "list_proposals", "list_orders", "list_products", "list_api_endpoints", "api_get",
    }


def test_tool_list_is_filtered_by_the_callers_rights(client, dolibarr):
    dolibarr.tokens[VALID_TOKEN] = User(rights=["societe.lire"])

    names = client.tool_names()

    assert {"list_thirdparties", "get_thirdparty"} <= names
    assert names.isdisjoint({"list_invoices", "get_invoice", "list_proposals", "list_orders", "list_products"})
    # Tools that are not bound to one module stay available; Dolibarr and the rights check decide per call.
    assert {"whoami", "my_permissions", "list_api_endpoints", "api_get"} <= names


def test_each_user_sees_the_tool_list_of_their_own_rights(client, dolibarr):
    other = "other-token-0123456789abcdef0123456789abcdef"
    dolibarr.tokens[other] = User(login="erika", firstname="Erika", lastname="Beispiel", rights=["produit.lire"])

    assert "list_products" in client.tool_names(token=other)
    assert "list_thirdparties" not in client.tool_names(token=other)
    assert "list_thirdparties" in client.tool_names(token=VALID_TOKEN)


def test_valid_token_is_accepted_without_the_sdk_resource_check(client, dolibarr):
    # restoauth/me does not report the resource a token was issued for (restoauth binds it at issue
    # time), so the server switches the MCP SDK's RFC 8707 check off explicitly. If an SDK update
    # turned it on, every valid token would be refused here with 401.
    from dolibarr_mcp_server.server import mcp

    r = client.call_tool("whoami")

    assert r.status_code == 200
    assert mcp.settings.auth.validate_token_resource is False
