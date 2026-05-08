#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _request(
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    json_body: dict | None = None,
    timeout: float = 120.0,
) -> dict | list:
    data = json.dumps(json_body).encode("utf-8") if json_body is not None else None
    if json_body is not None:
        headers = {**headers, "Content-Type": "application/json"}
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="replace")
        raise SystemExit(f"HTTP {e.code} {method} {url}: {err}") from e


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--base", default="http://localhost:8080", help="Service base URL")
    p.add_argument("--token", default="", help="Optional MEMORY_AUTH_TOKEN value")
    p.add_argument("--min-score", type=float, default=0.6, help="Minimum hit rate (0-1)")
    p.add_argument(
        "--fixture",
        default="fixtures/recall_fixture.json",
        help="Recall fixture JSON path (relative to repo root or absolute)",
    )
    args = p.parse_args()

    base = args.base.rstrip("/")
    fp = Path(args.fixture)
    fix_path = fp if fp.is_absolute() else ROOT / fp
    headers: dict[str, str] = {}
    if args.token:
        headers["Authorization"] = f"Bearer {args.token}"

    print("fixture:", fix_path)
    data = json.loads(fix_path.read_text(encoding="utf-8"))
    _request("GET", f"{base}/health", headers=headers)
    print("health OK")

    for convo in data["conversations"]:
        for t in convo["turns"]:
            payload = {
                "session_id": convo["session_id"],
                "user_id": convo["user_id"],
                "messages": t["messages"],
                "timestamp": t["timestamp"],
                "metadata": {},
            }
            resp = _request("POST", f"{base}/turns", headers=headers, json_body=payload)
            tid = resp.get("id") if isinstance(resp, dict) else None
            print("ingested turn:", convo["session_id"], tid)

    hits = 0
    total = 0
    for probe in data["probes"]:
        body = {**probe, "max_tokens": 512}
        resp = _request("POST", f"{base}/recall", headers=headers, json_body=body)
        if not isinstance(resp, dict):
            raise SystemExit("/recall returned non-object JSON")
        ctx = str(resp.get("context", "")).lower()
        print("\n--- probe ---")
        print("query:", probe["query"])
        print("user_id:", probe["user_id"])
        ok_parts = []
        for exp in probe["expects"]:
            total += 1
            if exp.lower() in ctx:
                hits += 1
                ok_parts.append(f"OK: {exp!r}")
            else:
                ok_parts.append(f"MISS: {exp!r}")
        print("checks:", "; ".join(ok_parts))
        print("context preview:", (ctx[:400] + "…") if len(ctx) > 400 else ctx)

    score = hits / max(1, total)
    print(f"\nFixture recall score: {hits}/{total} = {score:.2f}")
    if score < args.min_score:
        print(f"FAIL: below min {args.min_score}", file=sys.stderr)
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
