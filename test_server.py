from collections.abc import AsyncGenerator

import pytest
from mcp.client.session import ClientSession
from mcp.shared.memory import create_connected_server_and_client_session

import server


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def client_session(monkeypatch) -> AsyncGenerator[ClientSession]:
    def fake_http_get(url: str, expect_json: bool = True):
        if "programme/26072026/R1/C1/participants" in url:
            return {
                "participants": [
                    {
                        "numPmu": 1,
                        "nom": "Cheval A",
                        "age": 4,
                        "jockey": {"nom": "Jockey A"},
                        "entraineur": {"nom": "Entraineur A"},
                        "gainsParticipant": 12345,
                        "musique": "1a2a3a",
                        "dernierRapportDirect": {"rapport": 4.2},
                    }
                ]
            }
        if "programme/26072026/R1/C1" in url:
            return {
                "course": {
                    "numReunion": 1,
                    "numOrdre": 1,
                    "libelle": "Prix Test",
                    "heureDepart": "12:30",
                    "distance": 2400,
                    "discipline": "TROT",
                    "specialite": "ATTELE",
                    "montantPrix": 35000,
                    "nombreDeclaresPartants": 12,
                },
                "pronostics": {"favori": 1},
            }
        if "programme/26072026" in url:
            return {
                "programme": {
                    "reunions": [
                        {
                            "numOfficiel": 1,
                            "hippodrome": "Vincennes",
                            "courses": [
                                {
                                    "numOrdre": 1,
                                    "heureDepart": "12:30",
                                    "libelle": "Prix Test",
                                    "discipline": "TROT",
                                }
                            ],
                        }
                    ]
                }
            }
        if url == server.LEGAL_URL and not expect_json:
            return '<html><body><a href="/turf/static/sinformer/reglements/reglement_paris_internet.pdf">Règlement PMU des paris en ligne</a></body></html>'
        raise RuntimeError(f"unexpected URL: {url}")

    monkeypatch.setattr(server, "_http_get", fake_http_get)
    async with create_connected_server_and_client_session(server.app, raise_exceptions=True) as session:
        yield session


@pytest.mark.anyio
async def test_get_programme(client_session: ClientSession):
    result = await client_session.call_tool("get_programme", {"date": "2026-07-26"})
    data = result.structuredContent
    assert data["ok"] is True
    assert data["count_reunions"] == 1
    assert data["reunions"][0]["hippodrome"] == "Vincennes"


@pytest.mark.anyio
async def test_get_partants(client_session: ClientSession):
    result = await client_session.call_tool("get_partants", {"date": "26/07/2026", "reunion": 1, "course": 1})
    data = result.structuredContent
    assert data["ok"] is True
    assert data["count_participants"] == 1
    assert data["participants"][0]["nom"] == "Cheval A"


@pytest.mark.anyio
async def test_get_course_stats(client_session: ClientSession):
    result = await client_session.call_tool("get_course_stats", {"date": "26072026", "reunion": 1, "course": 1})
    data = result.structuredContent
    assert data["ok"] is True
    assert data["course"]["libelle"] == "Prix Test"
    assert data["participants"][0]["cote"] == 4.2
    assert data["warnings"]["partial_data"] is False


@pytest.mark.anyio
async def test_get_legal_docs(client_session: ClientSession):
    result = await client_session.call_tool("get_legal_docs", {})
    data = result.structuredContent
    assert data["ok"] is True
    assert data["count_documents"] == 1
    assert data["documents"][0]["url"].endswith("reglement_paris_internet.pdf")


@pytest.mark.anyio
async def test_invalid_date_returns_structured_error(client_session: ClientSession):
    result = await client_session.call_tool("get_programme", {"date": "2026/99/99"})
    data = result.structuredContent
    assert data["ok"] is False
    assert data["error"]["code"] == "invalid_input"
