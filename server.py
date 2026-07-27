from __future__ import annotations

import re
import time
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("PMU Turf Read-Only MCP", json_response=True)
app = mcp

PROGRAMME_URL = "https://offline.turfinfo.api.pmu.fr/rest/client/7/programme/{date}"
PARTANTS_URL = "https://offline.turfinfo.api.pmu.fr/rest/client/7/programme/{date}/R{reunion}/C{course}/participants"
INFOS_URL = "https://offline.turfinfo.api.pmu.fr/rest/client/7/programme/{date}/R{reunion}/C{course}"
LEGAL_URL = "https://www.pmu.fr/turf/informations-legales/"
TIMEOUT = httpx.Timeout(20.0, connect=10.0)
USER_AGENT = "pmu-readonly-mcp/0.3 (+research prototype)"
RETRIES = 3
RETRYABLE_STATUS_CODES = {408, 425, 429, 500, 502, 503, 504}


def _ok(data: Dict[str, Any]) -> Dict[str, Any]:
    return {"ok": True, **data}


def _err(message: str, *, code: str = "tool_error", details: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {"ok": False, "error": {"code": code, "message": message, "details": details or {}}}


def _normalize_date(date_str: str) -> str:
    s = date_str.strip()
    for fmt in ("%d%m%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt.strftime("%d%m%Y")
        except ValueError:
            continue
    digits = re.sub(r"\D", "", s)
    if len(digits) == 8:
        if digits[:4].isdigit() and 1900 <= int(digits[:4]) <= 2100:
            try:
                dt = datetime.strptime(digits, "%Y%m%d")
                return dt.strftime("%d%m%Y")
            except ValueError:
                pass
        try:
            dt = datetime.strptime(digits, "%d%m%Y")
            return dt.strftime("%d%m%Y")
        except ValueError:
            pass
    raise ValueError("date invalide ; formats acceptés : JJMMAAAA, AAAA-MM-JJ, JJ/MM/AAAA")


def _date_to_display(date_str: str) -> str:
    normalized = _normalize_date(date_str)
    dt = datetime.strptime(normalized, "%d%m%Y")
    return dt.strftime("%d/%m/%Y")


def _validate_positive_int(name: str, value: int) -> int:
    if not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} doit être un entier strictement positif")
    return value


def _http_get(url: str, expect_json: bool = True) -> Any:
    last_error: Optional[Exception] = None
    with httpx.Client(timeout=TIMEOUT, headers={"User-Agent": USER_AGENT, "Accept": "application/json, text/html;q=0.9, */*;q=0.8"}, follow_redirects=True) as client:
        for attempt in range(1, RETRIES + 1):
            try:
                resp = client.get(url)
                if resp.status_code in RETRYABLE_STATUS_CODES and attempt < RETRIES:
                    time.sleep(0.6 * attempt)
                    continue
                resp.raise_for_status()
                return resp.json() if expect_json else resp.text
            except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as exc:
                last_error = exc
                if attempt < RETRIES:
                    time.sleep(0.6 * attempt)
                    continue
                break
            except ValueError as exc:
                last_error = exc
                break
            except httpx.HTTPStatusError as exc:
                last_error = exc
                break
    raise RuntimeError(f"échec requête {url}: {last_error}")


def _safe_get(obj: Any, *path: Any) -> Any:
    cur = obj
    for key in path:
        if isinstance(cur, dict):
            cur = cur.get(key)
        elif isinstance(cur, list) and isinstance(key, int) and 0 <= key < len(cur):
            cur = cur[key]
        else:
            return None
        if cur is None:
            return None
    return cur


def _first_non_null(*values: Any) -> Any:
    for v in values:
        if v is not None and v != "":
            return v
    return None


def _extract_reunions(programme: Dict[str, Any]) -> List[Dict[str, Any]]:
    reunions = _first_non_null(
        _safe_get(programme, "programme", "reunions"),
        programme.get("reunions"),
        _safe_get(programme, "data", "reunions"),
    ) or []
    out: List[Dict[str, Any]] = []
    for r in reunions:
        courses = _first_non_null(r.get("courses"), r.get("listeCourses")) or []
        out.append({
            "numOfficiel": _first_non_null(r.get("numOfficiel"), r.get("numReunion"), r.get("numOrdre")),
            "libelleCourt": _first_non_null(r.get("libelleCourt"), r.get("hippodrome"), r.get("pays")),
            "hippodrome": _first_non_null(r.get("hippodrome"), r.get("libelleLong"), r.get("libelleCourt")),
            "pays": r.get("pays"),
            "timezone": r.get("timezone"),
            "officielle": r.get("officielle"),
            "nombreCourses": len(courses),
            "courses": [
                {
                    "numOrdre": c.get("numOrdre"),
                    "heureDepart": _first_non_null(c.get("heureDepart"), c.get("heureDepartUtc")),
                    "libelle": _first_non_null(c.get("libelle"), c.get("libelleCourt"), c.get("nom")),
                    "discipline": c.get("discipline"),
                    "specialite": c.get("specialite"),
                    "distance": c.get("distance"),
                    "montantPrix": _first_non_null(c.get("montantPrix"), c.get("allocation")),
                    "statut": c.get("statut"),
                }
                for c in courses
            ],
        })
    return out


def _extract_partants(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    participants = _first_non_null(
        data.get("participants"),
        data.get("partants"),
        _safe_get(data, "course", "participants"),
        _safe_get(data, "data", "participants"),
    ) or []
    out: List[Dict[str, Any]] = []
    for p in participants:
        cote = _first_non_null(
            p.get("cote"),
            p.get("dernierRapportDirect"),
            _safe_get(p, "dernierRapportDirect", "rapport"),
            _safe_get(p, "dernierRapportDirect", "valeur"),
        )
        out.append({
            "numPmu": _first_non_null(p.get("numPmu"), p.get("numeroPmu"), p.get("numPmuInt"), p.get("numCheval")),
            "nom": p.get("nom"),
            "statut": _first_non_null(p.get("statut"), p.get("indicateurInedit"), p.get("indicateurNonPartant")),
            "age": p.get("age"),
            "sexe": p.get("sexe"),
            "race": p.get("race"),
            "oeilleres": p.get("oeilleres"),
            "driver": _first_non_null(_safe_get(p, "driver", "nom"), _safe_get(p, "driver", "prenomNom"), p.get("driver")),
            "jockey": _first_non_null(_safe_get(p, "jockey", "nom"), _safe_get(p, "jockey", "prenomNom"), p.get("jockey")),
            "entraineur": _first_non_null(_safe_get(p, "entraineur", "nom"), p.get("entraineur")),
            "proprietaire": _first_non_null(_safe_get(p, "proprietaire", "nom"), p.get("proprietaire")),
            "musique": _first_non_null(p.get("dernieresPerformances"), p.get("musique"), p.get("performances")),
            "gainsParticipant": _first_non_null(p.get("gainsParticipant"), p.get("gainsCarriere"), p.get("gains")),
            "cote": cote,
        })
    return out


def _extract_course_core(info: Dict[str, Any]) -> Dict[str, Any]:
    return _first_non_null(
        info.get("course"),
        _safe_get(info, "data", "course"),
        info,
    ) or {}


def _extract_course_stats(info: Dict[str, Any], participants: Dict[str, Any]) -> Dict[str, Any]:
    course = _extract_course_core(info)
    pronostic = _first_non_null(info.get("pronostics"), course.get("pronostics"), _safe_get(info, "data", "pronostics")) or {}
    return {
        "course": {
            "numReunion": _first_non_null(course.get("numReunion"), _safe_get(course, "reunion", "numOfficiel")),
            "numOrdre": course.get("numOrdre"),
            "libelle": _first_non_null(course.get("libelle"), course.get("libelleCourt"), course.get("nom")),
            "heureDepart": _first_non_null(course.get("heureDepart"), course.get("heureDepartUtc")),
            "distance": course.get("distance"),
            "discipline": course.get("discipline"),
            "specialite": course.get("specialite"),
            "montantPrix": _first_non_null(course.get("montantPrix"), course.get("allocation")),
            "conditionSexe": course.get("conditionSexe"),
            "conditionAge": course.get("conditionAge"),
            "corde": course.get("corde"),
            "hippodrome": _first_non_null(_safe_get(course, "reunion", "hippodrome"), course.get("hippodrome")),
            "meteo": course.get("meteo"),
            "pariOuvert": course.get("pariOuvert"),
            "nombreDeclaresPartants": course.get("nombreDeclaresPartants"),
            "incidents": course.get("incidents"),
        },
        "pronostics": pronostic,
        "participants": _extract_partants(participants),
        "meta": {
            "fallbackUsed": True,
            "infoKeys": sorted(list(info.keys()))[:100] if isinstance(info, dict) else [],
            "participantsKeys": sorted(list(participants.keys()))[:100] if isinstance(participants, dict) else [],
        },
    }


def _parse_legal_docs(html: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    docs: List[Dict[str, Any]] = []
    for a in soup.select("a[href]"):
        href = (a.get("href") or "").strip()
        text = " ".join(a.get_text(" ", strip=True).split())
        if not href:
            continue
        full_url = urljoin(LEGAL_URL, href)
        hay = f"{text} {href}".lower()
        if any(token in hay for token in ["pdf", "reglement", "conditions", "taux applicables", "politique"]):
            docs.append({"title": text or full_url.rsplit("/", 1)[-1], "url": full_url})
    uniq: List[Dict[str, Any]] = []
    seen = set()
    for doc in docs:
        key = (doc["title"], doc["url"])
        if key not in seen:
            seen.add(key)
            uniq.append(doc)
    return uniq


@mcp.tool()
def get_programme(date: str) -> Dict[str, Any]:
    try:
        normalized = _normalize_date(date)
        payload = _http_get(PROGRAMME_URL.format(date=normalized), expect_json=True)
        reunions = _extract_reunions(payload)
        return _ok({
            "date": _date_to_display(date),
            "source": PROGRAMME_URL.format(date=normalized),
            "count_reunions": len(reunions),
            "reunions": reunions,
        })
    except ValueError as exc:
        return _err(str(exc), code="invalid_input", details={"field": "date", "value": date})
    except Exception as exc:
        return _err("impossible de récupérer le programme", code="upstream_failure", details={"date": date, "reason": str(exc)})


@mcp.tool()
def get_partants(date: str, reunion: int, course: int) -> Dict[str, Any]:
    try:
        normalized = _normalize_date(date)
        reunion = _validate_positive_int("reunion", reunion)
        course = _validate_positive_int("course", course)
        url = PARTANTS_URL.format(date=normalized, reunion=reunion, course=course)
        payload = _http_get(url, expect_json=True)
        participants = _extract_partants(payload)
        return _ok({
            "date": _date_to_display(date),
            "reunion": reunion,
            "course": course,
            "source": url,
            "count_participants": len(participants),
            "participants": participants,
        })
    except ValueError as exc:
        return _err(str(exc), code="invalid_input", details={"date": date, "reunion": reunion, "course": course})
    except Exception as exc:
        return _err("impossible de récupérer les partants", code="upstream_failure", details={"date": date, "reunion": reunion, "course": course, "reason": str(exc)})


@mcp.tool()
def get_course_stats(date: str, reunion: int, course: int) -> Dict[str, Any]:
    try:
        normalized = _normalize_date(date)
        reunion = _validate_positive_int("reunion", reunion)
        course = _validate_positive_int("course", course)
        info_url = INFOS_URL.format(date=normalized, reunion=reunion, course=course)
        partants_url = PARTANTS_URL.format(date=normalized, reunion=reunion, course=course)
        info_errors: List[str] = []
        participants_errors: List[str] = []
        try:
            info = _http_get(info_url, expect_json=True)
        except Exception as exc:
            info = {}
            info_errors.append(str(exc))
        try:
            participants = _http_get(partants_url, expect_json=True)
        except Exception as exc:
            participants = {}
            participants_errors.append(str(exc))
        if not info and not participants:
            return _err(
                "impossible de récupérer les données de course",
                code="upstream_failure",
                details={"date": date, "reunion": reunion, "course": course, "sources": {"course": info_url, "participants": partants_url}, "errors": info_errors + participants_errors},
            )
        result = _extract_course_stats(info, participants)
        result.update({
            "date": _date_to_display(date),
            "reunion": reunion,
            "course_number": course,
            "sources": {"course": info_url, "participants": partants_url},
            "warnings": {
                "course_fetch_errors": info_errors,
                "participants_fetch_errors": participants_errors,
                "partial_data": bool(info_errors or participants_errors),
            },
        })
        return _ok(result)
    except ValueError as exc:
        return _err(str(exc), code="invalid_input", details={"date": date, "reunion": reunion, "course": course})
    except Exception as exc:
        return _err("impossible de récupérer les statistiques de course", code="upstream_failure", details={"date": date, "reunion": reunion, "course": course, "reason": str(exc)})


@mcp.tool()
def get_legal_docs() -> Dict[str, Any]:
    try:
        html = _http_get(LEGAL_URL, expect_json=False)
        docs = _parse_legal_docs(html)
        if not docs:
            return _err("aucun document légal détecté sur la page", code="parse_failure", details={"source": LEGAL_URL})
        return _ok({"source": LEGAL_URL, "count_documents": len(docs), "documents": docs})
    except Exception as exc:
        return _err("impossible de récupérer les documents légaux", code="upstream_failure", details={"source": LEGAL_URL, "reason": str(exc)})


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
