#!/usr/bin/env python3
"""Credential-safe, bounded Zotero Web API v3 helper for library builds."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

API = "https://api.zotero.org"
UA = "codex-build-zotero-library/1.0"
KEYCHAIN_SERVICE = "codex-zotero-mcp"


class ApiError(RuntimeError):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def keychain_value(account: str) -> str | None:
    try:
        proc = subprocess.run(
            ["/usr/bin/security", "find-generic-password", "-s", KEYCHAIN_SERVICE,
             "-a", account, "-w"],
            check=True, capture_output=True, text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None
    return proc.stdout.strip() or None


def credentials() -> tuple[str, str, str]:
    key = os.environ.get("ZOTERO_API_KEY") or keychain_value("api-key")
    library_id = os.environ.get("ZOTERO_LIBRARY_ID") or keychain_value("library-id")
    library_type = os.environ.get("ZOTERO_LIBRARY_TYPE", "user")
    if not key:
        raise RuntimeError(
            "no Zotero API key; set ZOTERO_API_KEY or configure the "
            f"{KEYCHAIN_SERVICE!r} Keychain service"
        )
    if library_type not in {"user", "group"}:
        raise RuntimeError("ZOTERO_LIBRARY_TYPE must be 'user' or 'group'")
    return key, library_type, library_id or ""


def parse_library(value: str | None, default_type: str, default_id: str) -> tuple[str, str]:
    if value:
        try:
            kind, library_id = value.split(":", 1)
        except ValueError as exc:
            raise RuntimeError("library must be user:<id> or group:<id>") from exc
    else:
        kind, library_id = default_type, default_id
    if kind not in {"user", "group"} or not library_id:
        raise RuntimeError("library must be user:<id> or group:<id>")
    return kind, library_id


def prefix(kind: str, library_id: str) -> str:
    return f"/{kind}s/{urllib.parse.quote(library_id, safe='')}"


def request(
    path: str,
    key: str,
    method: str = "GET",
    body: Any | None = None,
    extra_headers: dict[str, str] | None = None,
) -> tuple[int, Any, dict[str, str]]:
    data = None
    headers = {
        "User-Agent": UA,
        "Zotero-API-Key": key,
        "Zotero-API-Version": "3",
        "Accept": "application/json",
    }
    if body is not None:
        data = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        headers["Content-Type"] = "application/json"
    headers.update(extra_headers or {})
    req = urllib.request.Request(API + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=45) as response:
            raw = response.read()
            parsed = json.loads(raw) if raw else None
            return response.status, parsed, dict(response.headers.items())
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(raw)
        except json.JSONDecodeError:
            detail = raw[:1000]
        raise ApiError(exc.code, f"Zotero API {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise ApiError(0, f"Zotero API network error: {exc.reason}") from exc


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"cannot read JSON from {path}: {exc}") from exc


def request_paginated(path: str, key: str) -> list[dict[str, Any]]:
    """Read every API page, rejecting foreign or looping continuation links."""
    items: list[dict[str, Any]] = []
    visited: set[str] = set()
    while path:
        if path in visited:
            raise RuntimeError("Zotero pagination repeated a page")
        visited.add(path)
        _, page, headers = request(path, key)
        if not isinstance(page, list) or any(not isinstance(item, dict) for item in page):
            raise RuntimeError("Zotero list response must be an array of objects")
        items.extend(page)
        headers = {name.lower(): value for name, value in headers.items()}
        next_url = ""
        for link in headers.get("link", "").split(","):
            match = re.search(r'<([^>]+)>;\s*rel="?next"?', link)
            if match:
                next_url = match.group(1)
                break
        if next_url:
            parsed = urllib.parse.urlsplit(urllib.parse.urljoin(API + path, next_url))
            if f"{parsed.scheme}://{parsed.netloc}" != API:
                raise RuntimeError("Zotero pagination returned a foreign destination")
            path = parsed.path + ("?" + parsed.query if parsed.query else "")
        else:
            total = headers.get("total-results", "")
            if total.isdigit() and len(items) < int(total):
                raise RuntimeError("Zotero list response is incomplete and has no next page")
            path = ""
    return items


def write_output(value: Any, path: Path | None) -> None:
    rendered = json.dumps(value, indent=2, ensure_ascii=False) + "\n"
    if path:
        path.write_text(rendered, encoding="utf-8")
        print(path)
    else:
        sys.stdout.write(rendered)


def unwrap_items(payload: Any) -> tuple[list[dict[str, Any]], list[str]]:
    if not isinstance(payload, list) or not payload:
        raise RuntimeError("input must be a nonempty JSON array")
    items: list[dict[str, Any]] = []
    candidate_ids: list[str] = []
    for index, entry in enumerate(payload):
        if not isinstance(entry, dict):
            raise RuntimeError(f"input element {index} is not an object")
        if "item" in entry:
            item = entry.get("item")
            candidate_id = str(entry.get("candidate_id", ""))
        else:
            item = entry
            candidate_id = ""
        if not isinstance(item, dict) or not item.get("itemType"):
            raise RuntimeError(f"input element {index} lacks item.itemType")
        items.append(item)
        candidate_ids.append(candidate_id)
    if len(items) > 50:
        raise RuntimeError("Zotero accepts at most 50 items per write request")
    return items, candidate_ids


def normalized_write_maps(response: Any) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    if not isinstance(response, dict):
        return {}, {}, {"_response": "non-object response"}
    successful = response.get("successful") or response.get("success") or {}
    unchanged = response.get("unchanged") or {}
    failed = response.get("failed") or {}
    return successful, unchanged, failed


def add_common_library(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--library", help="user:<id> or group:<id>; defaults to configured library")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="command", required=True)

    subs.add_parser("key-info", help="verify the configured key without printing it")

    p = subs.add_parser("collections", help="list collections")
    add_common_library(p)
    p.add_argument("--limit", type=int, default=100)

    p = subs.add_parser("inventory", help="read a complete compact top-level library inventory")
    add_common_library(p)
    p.add_argument("--output", type=Path)

    p = subs.add_parser("collection-items", help="list top-level items in a collection")
    add_common_library(p)
    p.add_argument("--collection", required=True)
    p.add_argument("--limit", type=int, default=100)

    p = subs.add_parser("search-items", help="search a library")
    add_common_library(p)
    p.add_argument("--query", required=True)
    p.add_argument("--qmode", choices=("titleCreatorYear", "everything"), default="everything")
    p.add_argument("--limit", type=int, default=50)

    p = subs.add_parser("get-items", help="fetch specific item keys")
    add_common_library(p)
    p.add_argument("--keys", required=True)

    p = subs.add_parser("item-template", help="fetch an empty item template")
    p.add_argument("--type", required=True)

    p = subs.add_parser("create-collection", help="create one or more collections")
    add_common_library(p)
    p.add_argument("--input", required=True, type=Path)
    p.add_argument("--output", type=Path)

    p = subs.add_parser("create-items", help="create up to 50 items")
    add_common_library(p)
    p.add_argument("--input", required=True, type=Path)
    p.add_argument("--output", type=Path)

    p = subs.add_parser("patch-item", help="version-guarded partial update of one item")
    add_common_library(p)
    p.add_argument("--key", required=True)
    p.add_argument("--version", required=True, type=int)
    p.add_argument("--input", required=True, type=Path)
    p.add_argument("--output", type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        api_key, default_type, default_id = credentials()
        if args.command == "key-info":
            status, value, _ = request("/keys/current", api_key)
            safe = {
                "http_status": status,
                "authenticated": isinstance(value, dict) and bool(value.get("key")),
                "username": value.get("username") if isinstance(value, dict) else None,
                "access": value.get("access") if isinstance(value, dict) else None,
            }
            write_output(safe, None)
            return 0

        if args.command == "item-template":
            query = urllib.parse.urlencode({"itemType": args.type})
            _, value, _ = request(f"/items/new?{query}", api_key)
            write_output(value, None)
            return 0

        kind, library_id = parse_library(args.library, default_type, default_id)
        base = prefix(kind, library_id)

        if args.command == "inventory":
            values = request_paginated(f"{base}/items/top?limit=100&format=json", api_key)
            inventory = []
            for value in values:
                item = value.get("data", value)
                if not isinstance(item, dict):
                    raise RuntimeError("Zotero inventory item has malformed metadata")
                if item.get("itemType") in {"attachment", "note"}:
                    continue
                row = {field: item.get(field) for field in (
                    "key", "itemType", "title", "creators", "date", "publicationTitle", "publisher",
                    "ISBN", "DOI", "collections",
                )}
                meta = value.get("meta")
                row["child_count"] = meta.get("numChildren") if isinstance(meta, dict) else None
                inventory.append(row)
            write_output(inventory, args.output)
            return 0

        if args.command == "collections":
            query = urllib.parse.urlencode({"limit": max(1, min(args.limit, 100)), "format": "json"})
            value = request_paginated(f"{base}/collections?{query}", api_key)
            write_output(value, None)
            return 0
        if args.command == "collection-items":
            collection = urllib.parse.quote(args.collection, safe="")
            query = urllib.parse.urlencode({"limit": max(1, min(args.limit, 100)), "format": "json"})
            value = request_paginated(f"{base}/collections/{collection}/items/top?{query}", api_key)
            write_output(value, None)
            return 0
        if args.command == "search-items":
            query = urllib.parse.urlencode({
                "q": args.query,
                "qmode": args.qmode,
                "limit": max(1, min(args.limit, 100)),
                "format": "json",
            })
            value = request_paginated(f"{base}/items/top?{query}", api_key)
            write_output(value, None)
            return 0
        if args.command == "get-items":
            keys = [part.strip() for part in args.keys.split(",") if part.strip()]
            if not keys or len(keys) > 50:
                raise RuntimeError("--keys must contain 1 to 50 item keys")
            query = urllib.parse.urlencode({"itemKey": ",".join(keys), "limit": 100, "format": "json"})
            _, value, _ = request(f"{base}/items?{query}", api_key)
            write_output(value, None)
            return 0
        if args.command == "create-collection":
            payload = load_json(args.input)
            if not isinstance(payload, list) or not 1 <= len(payload) <= 50:
                raise RuntimeError("collection input must be an array of 1 to 50 objects")
            token = secrets.token_hex(16)
            status, value, headers = request(
                f"{base}/collections", api_key, "POST", payload,
                {"Zotero-Write-Token": token},
            )
            result = {
                "operation": "create-collection",
                "library": f"{kind}:{library_id}",
                "request_count": len(payload),
                "request_sha256": hashlib.sha256(
                    json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
                ).hexdigest(),
                "http_status": status,
                "response": value,
                "written_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "last_modified_version": headers.get("Last-Modified-Version"),
            }
            write_output(result, args.output)
            return 1 if normalized_write_maps(value)[2] else 0
        if args.command == "create-items":
            items, candidate_ids = unwrap_items(load_json(args.input))
            token = secrets.token_hex(16)
            status, value, headers = request(
                f"{base}/items", api_key, "POST", items,
                {"Zotero-Write-Token": token},
            )
            successful, unchanged, failed = normalized_write_maps(value)
            result = {
                "operation": "create-items",
                "library": f"{kind}:{library_id}",
                "request_count": len(items),
                "candidate_ids": candidate_ids,
                "request_sha256": hashlib.sha256(
                    json.dumps(items, sort_keys=True, ensure_ascii=False).encode("utf-8")
                ).hexdigest(),
                "http_status": status,
                "successful": successful,
                "unchanged": unchanged,
                "failed": failed,
                "response": value,
                "written_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "last_modified_version": headers.get("Last-Modified-Version"),
            }
            write_output(result, args.output)
            return 1 if failed or len(successful) + len(unchanged) != len(items) else 0
        if args.command == "patch-item":
            patch = load_json(args.input)
            if not isinstance(patch, dict) or not patch:
                raise RuntimeError("patch input must be a nonempty JSON object")
            item_key = urllib.parse.quote(args.key, safe="")
            status, value, headers = request(
                f"{base}/items/{item_key}", api_key, "PATCH", patch,
                {"If-Unmodified-Since-Version": str(args.version)},
            )
            result = {
                "operation": "patch-item",
                "library": f"{kind}:{library_id}",
                "item_key": args.key,
                "prior_version": args.version,
                "http_status": status,
                "response": value,
                "written_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "last_modified_version": headers.get("Last-Modified-Version"),
            }
            write_output(result, args.output)
            return 0
        raise RuntimeError(f"unsupported command: {args.command}")
    except (RuntimeError, ApiError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 2 if not isinstance(exc, ApiError) else 1


if __name__ == "__main__":
    raise SystemExit(main())
