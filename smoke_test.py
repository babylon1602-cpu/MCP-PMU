import argparse
import json
import sys

from server import get_course_stats, get_legal_docs, get_partants, get_programme


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test local du serveur PMU Turf Read-Only MCP")
    parser.add_argument("--date", default="2026-07-26", help="Date test ; ex: 2026-07-26")
    parser.add_argument("--reunion", type=int, default=1, help="Numéro de réunion")
    parser.add_argument("--course", type=int, default=1, help="Numéro de course")
    args = parser.parse_args()

    checks = {
        "get_programme": get_programme(args.date),
        "get_partants": get_partants(args.date, args.reunion, args.course),
        "get_course_stats": get_course_stats(args.date, args.reunion, args.course),
        "get_legal_docs": get_legal_docs(),
    }

    failed = []
    for name, result in checks.items():
        status = result.get("ok") is True
        print(f"[{ 'OK' if status else 'FAIL' }] {name}")
        if not status:
            failed.append({"tool": name, "error": result.get("error")})

    print("\nRésumé JSON:")
    print(json.dumps(checks, ensure_ascii=False, indent=2)[:12000])

    if failed:
        print("\nSmoke test échoué pour:", ", ".join(x["tool"] for x in failed), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
