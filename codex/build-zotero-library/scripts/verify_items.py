#!/usr/bin/env python3
"""Deterministically verify Zotero item identity from ISBN or DOI metadata."""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from zotero_api import credentials, parse_library, prefix, request as zotero_request, request_paginated

UA = "codex-build-zotero-library-verifier/1.0"
TIMEOUT = 25
PAUSE = 0.25


@dataclass
class Fetch:
    status: str
    value: Any = None
    detail: str = ""


def fetch_json(url: str) -> Fetch:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
            return Fetch("ok", json.load(response))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return Fetch("not_found", detail="HTTP 404")
        return Fetch("error", detail=f"HTTP {exc.code}")
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        return Fetch("error", detail=exc.__class__.__name__)


def normalize(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = "".join(ch if ch.isalnum() else " " for ch in text.lower())
    return re.sub(r"\s+", " ", text).strip()


def main_title(value: str) -> str:
    return normalize(re.split(r"[:;]|\s[-–—]\s", value or "", maxsplit=1)[0])


def title_matches(claimed: str, found: str) -> bool:
    claimed_full, found_full = normalize(claimed), normalize(found)
    if not claimed_full or not found_full:
        return False
    claimed_main, found_main = main_title(claimed), main_title(found)
    if claimed_main and found_main and (
        claimed_main == found_main
        or (len(claimed_main) >= 12 and claimed_main in found_full)
        or (len(found_main) >= 12 and found_main in claimed_full)
    ):
        return True
    return difflib.SequenceMatcher(None, claimed_full, found_full).ratio() >= 0.82


def year_of(value: Any) -> int | None:
    match = re.search(r"\b(1[5-9]\d{2}|20\d{2})\b", str(value or ""))
    return int(match.group(1)) if match else None


def isbn_ok(value: str) -> bool:
    digits = re.sub(r"[^0-9Xx]", "", value)
    if len(digits) == 10:
        total = sum((10 - i) * (10 if ch in "Xx" else int(ch)) for i, ch in enumerate(digits))
        return total % 11 == 0
    if len(digits) == 13 and digits.isdigit():
        total = sum(int(ch) * (1 if i % 2 == 0 else 3) for i, ch in enumerate(digits))
        return total % 10 == 0
    return False


def isbns_of(value: Any) -> list[str]:
    candidates = re.findall(r"(?<!\d)(?:97[89][0-9 -]{10,16}|[0-9][0-9Xx -]{8,15})(?!\d)", str(value or ""))
    cleaned: list[str] = []
    for candidate in candidates:
        isbn = re.sub(r"[^0-9Xx]", "", candidate)
        if len(isbn) in {10, 13} and isbn not in cleaned:
            cleaned.append(isbn)
    return cleaned


def normalize_doi(value: Any) -> str:
    doi = str(value or "").strip()
    doi = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", doi, flags=re.I)
    return doi.strip().rstrip(".")


def creator_names(item: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for creator in item.get("creators") or []:
        if not isinstance(creator, dict):
            continue
        if creator.get("creatorType") not in {"author", "editor", "bookAuthor"}:
            continue
        name = creator.get("lastName") or creator.get("name")
        if name:
            names.append(str(name))
    return names


def record(source: str, title: str, authors: list[str], year: Any) -> dict[str, Any]:
    return {"source": source, "title": title, "authors": authors, "year": year}


def openlibrary_edition(isbn: str) -> Fetch:
    fetched = fetch_json(f"https://openlibrary.org/isbn/{isbn}.json")
    if fetched.status != "ok":
        return fetched
    data = fetched.value
    title = data.get("title", "")
    if data.get("subtitle"):
        title += ": " + data["subtitle"]
    authors: list[str] = []
    if data.get("by_statement"):
        authors.append(str(data["by_statement"]))
    for author in data.get("authors") or []:
        key = author.get("key") if isinstance(author, dict) else None
        if not key:
            continue
        author_fetch = fetch_json(f"https://openlibrary.org{key}.json")
        if author_fetch.status == "ok" and author_fetch.value.get("name"):
            authors.append(str(author_fetch.value["name"]))
    return Fetch("ok", [record("openlibrary-edition", title, authors, year_of(data.get("publish_date")))])


def openlibrary_search(isbn: str) -> Fetch:
    query = urllib.parse.urlencode({
        "q": f"isbn:{isbn}",
        "fields": "title,subtitle,author_name,first_publish_year,publish_year,isbn",
        "limit": 5,
    })
    fetched = fetch_json(f"https://openlibrary.org/search.json?{query}")
    if fetched.status != "ok":
        return fetched
    records = []
    for item in fetched.value.get("docs") or []:
        identifiers = {re.sub(r"[^0-9Xx]", "", value) for value in item.get("isbn") or []}
        if identifiers and isbn not in identifiers:
            continue
        title = item.get("title", "")
        if item.get("subtitle"):
            title += ": " + item["subtitle"]
        years = list(item.get("publish_year") or [])
        if item.get("first_publish_year"):
            years.append(item["first_publish_year"])
        records.append(record("openlibrary-search", title, item.get("author_name") or [], years))
    return Fetch("ok" if records else "not_found", records)


def google_books(isbn: str) -> Fetch:
    query = urllib.parse.urlencode({"q": f"isbn:{isbn}", "country": "US"})
    fetched = fetch_json(f"https://www.googleapis.com/books/v1/volumes?{query}")
    if fetched.status != "ok":
        return fetched
    if fetched.value.get("error"):
        return Fetch("error", detail="API error or quota")
    records = []
    for item in fetched.value.get("items") or []:
        volume = item.get("volumeInfo") or {}
        identifiers = {
            re.sub(r"[^0-9Xx]", "", str(identifier.get("identifier", "")))
            for identifier in volume.get("industryIdentifiers") or []
            if isinstance(identifier, dict)
        }
        if isbn not in identifiers:
            continue
        title = volume.get("title", "")
        if volume.get("subtitle"):
            title += ": " + volume["subtitle"]
        records.append(record(
            "google-books", title, volume.get("authors") or [],
            year_of(volume.get("publishedDate")),
        ))
    return Fetch("ok" if records else "not_found", records)


def harvard_library(isbn: str) -> Fetch:
    query = urllib.parse.urlencode({"identifier": isbn, "limit": 5})
    fetched = fetch_json(f"https://api.lib.harvard.edu/v2/items.json?{query}")
    if fetched.status != "ok":
        return fetched
    mods = (fetched.value.get("items") or {}).get("mods") if isinstance(fetched.value.get("items"), dict) else None
    if not mods:
        return Fetch("not_found")
    records = []
    for item in mods if isinstance(mods, list) else [mods]:
        title_info = item.get("titleInfo") or {}
        title_info = title_info[0] if isinstance(title_info, list) else title_info
        title = str(title_info.get("title", ""))
        if title_info.get("subTitle"):
            title += ": " + str(title_info["subTitle"])
        names: list[str] = []
        raw_names = item.get("name") or []
        for name in raw_names if isinstance(raw_names, list) else [raw_names]:
            if not isinstance(name, dict):
                continue
            parts = name.get("namePart") or []
            for part in parts if isinstance(parts, list) else [parts]:
                if isinstance(part, str):
                    names.append(part)
                elif isinstance(part, dict) and part.get("@type") != "date" and part.get("#text"):
                    names.append(str(part["#text"]))
        years: list[int] = []
        origins = item.get("originInfo") or []
        for origin in origins if isinstance(origins, list) else [origins]:
            if not isinstance(origin, dict):
                continue
            issued = origin.get("dateIssued") or []
            for value in issued if isinstance(issued, list) else [issued]:
                if isinstance(value, dict):
                    value = value.get("#text")
                found = year_of(value)
                if found:
                    years.append(found)
        if title:
            records.append(record("harvard-library", title, names, years))
    return Fetch("ok" if records else "not_found", records)


def crossref(doi: str) -> Fetch:
    fetched = fetch_json(f"https://api.crossref.org/works/{urllib.parse.quote(doi, safe='')}")
    if fetched.status != "ok":
        return fetched
    message = fetched.value.get("message") if isinstance(fetched.value, dict) else None
    if not isinstance(message, dict):
        return Fetch("not_found")
    found_doi = normalize_doi(message.get("DOI"))
    if found_doi and found_doi.lower() != doi.lower():
        return Fetch("not_found")
    title = " ".join(message.get("title") or [])
    if message.get("subtitle"):
        title += ": " + " ".join(message["subtitle"])
    authors = [
        " ".join(part for part in (author.get("given"), author.get("family")) if part)
        for author in message.get("author") or [] if isinstance(author, dict)
    ]
    year = None
    for field in ("published-print", "published-online", "issued", "created"):
        parts = (message.get(field) or {}).get("date-parts")
        if parts and parts[0]:
            year = parts[0][0]
            break
    return Fetch("ok", [record("crossref", title, authors, year)])


def compare(item: dict[str, Any], source: dict[str, Any]) -> tuple[bool, list[str], list[str]]:
    problems: list[str] = []
    verified = ["identifier"]
    if title_matches(str(item.get("title", "")), str(source.get("title", ""))):
        verified.append("title")
    else:
        problems.append(f"title mismatch: {source.get('title')!r}")

    claimed_year = year_of(item.get("date"))
    source_year = source.get("year")
    source_years = source_year if isinstance(source_year, list) else [source_year]
    source_years = [int(value) for value in source_years if isinstance(value, (int, str)) and str(value).isdigit()]
    if claimed_year and source_years:
        if any(abs(claimed_year - value) <= 1 for value in source_years):
            verified.append("date")
        else:
            problems.append(f"year mismatch: claimed {claimed_year}, source {source_years}")

    claimed_creators = creator_names(item)
    source_creators = normalize(" ".join(str(value) for value in source.get("authors") or []))
    if claimed_creators and source_creators:
        missing = [name for name in claimed_creators
                   if not normalize(name) or f" {normalize(name)} " not in f" {source_creators} "]
        if missing:
            problems.append("creator mismatch: " + ", ".join(missing))
        else:
            verified.append("creators")
    return not problems, verified, problems


def verify_identifier(
    item: dict[str, Any],
    identifier_type: str,
    identifier: str,
    resolvers: list[Callable[[str], Fetch]],
) -> dict[str, Any]:
    attempts: list[dict[str, Any]] = []
    found_any = False
    available_any = False
    for resolver in resolvers:
        try:
            fetched = resolver(identifier)
            if fetched.status == "ok" and (
                not isinstance(fetched.value, list)
                or any(not isinstance(source, dict) for source in fetched.value)
            ):
                fetched = Fetch("error", detail="malformed resolver records")
        except (AttributeError, TypeError, ValueError, KeyError) as exc:
            fetched = Fetch("error", detail=f"malformed resolver response ({type(exc).__name__})")
        time.sleep(PAUSE)
        attempt: dict[str, Any] = {"resolver": resolver.__name__, "status": fetched.status}
        if fetched.detail:
            attempt["detail"] = fetched.detail
        if fetched.status == "error":
            attempts.append(attempt)
            continue
        available_any = True
        if fetched.status == "not_found":
            attempts.append(attempt)
            continue
        found_any = True
        comparisons = []
        for source in fetched.value or []:
            ok, verified_fields, problems = compare(item, source)
            comparisons.append({
                "source": source.get("source"),
                "title": source.get("title"),
                "year": source.get("year"),
                "verified_fields": verified_fields,
                "problems": problems,
            })
            if ok:
                attempt["comparisons"] = comparisons
                attempts.append(attempt)
                return {
                    "verdict": "PASS",
                    "identifier": f"{identifier_type} {identifier}",
                    "matched_source": source.get("source"),
                    "verified_fields": verified_fields,
                    "attempts": attempts,
                }
        attempt["comparisons"] = comparisons
        attempts.append(attempt)
    if found_any:
        verdict = "MISMATCH"
    elif available_any:
        verdict = "UNRESOLVED"
    else:
        verdict = "UNAVAILABLE"
    return {
        "verdict": verdict,
        "identifier": f"{identifier_type} {identifier}",
        "matched_source": "",
        "verified_fields": [],
        "attempts": attempts,
    }


def verify_item(item: dict[str, Any]) -> dict[str, Any]:
    base = {"key": item.get("key", ""), "title": item.get("title", "")}
    isbns = isbns_of(item.get("ISBN"))
    valid_isbns = [isbn for isbn in isbns if isbn_ok(isbn)]
    doi = normalize_doi(item.get("DOI"))

    results = []
    for isbn in valid_isbns:
        result = verify_identifier(
            item, "ISBN", isbn,
            [openlibrary_edition, openlibrary_search, google_books, harvard_library],
        )
        results.append(result)
        if result["verdict"] == "PASS":
            return {**base, **result}
    if doi:
        result = verify_identifier(item, "DOI", doi, [crossref])
        results.append(result)
        if result["verdict"] == "PASS":
            return {**base, **result}

    if isbns and not valid_isbns and not doi:
        return {
            **base, "verdict": "BAD_IDENTIFIER", "identifier": "ISBN " + ", ".join(isbns),
            "matched_source": "", "verified_fields": [],
            "attempts": [], "detail": "all supplied ISBN values fail checksum validation",
        }
    if not isbns and not doi:
        return {
            **base, "verdict": "NO_IDENTIFIER", "identifier": "",
            "matched_source": "", "verified_fields": [], "attempts": [],
            "detail": "no ISBN or DOI; requires documented manual verification",
        }
    priority = {"MISMATCH": 3, "UNRESOLVED": 2, "UNAVAILABLE": 1}
    chosen = max(results, key=lambda result: priority.get(result["verdict"], 0))
    return {**base, **chosen}


def load_input(path: Path | None, stdin_mode: bool) -> list[dict[str, Any]]:
    if stdin_mode:
        payload = json.load(sys.stdin)
    elif path:
        payload = json.loads(path.read_text(encoding="utf-8"))
    else:
        raise RuntimeError("provide --input, --stdin, --keys, or --collection")
    if not isinstance(payload, list):
        raise RuntimeError("item input must be a JSON array")
    items = []
    for index, entry in enumerate(payload):
        if not isinstance(entry, dict):
            raise RuntimeError(f"input element {index} is not an object")
        item = entry.get("item", entry)
        if not isinstance(item, dict):
            raise RuntimeError(f"input element {index} has no item object")
        items.append(item)
    return items


def fetch_zotero_items(library: str | None, keys: str | None, collection: str | None) -> list[dict[str, Any]]:
    api_key, default_type, default_id = credentials()
    kind, library_id = parse_library(library, default_type, default_id)
    base = prefix(kind, library_id)
    if keys:
        key_list = [part.strip() for part in keys.split(",") if part.strip()]
        if not key_list or len(key_list) > 50:
            raise RuntimeError("--keys must contain 1 to 50 item keys")
        query = urllib.parse.urlencode({"itemKey": ",".join(key_list), "limit": 100, "format": "json"})
        _, payload, _ = zotero_request(f"{base}/items?{query}", api_key)
    elif collection:
        collection_key = urllib.parse.quote(collection, safe="")
        query = urllib.parse.urlencode({"limit": 100, "format": "json"})
        payload = request_paginated(f"{base}/collections/{collection_key}/items/top?{query}", api_key)
    else:
        raise RuntimeError("provide --keys or --collection")
    if not isinstance(payload, list) or any(not isinstance(entry, dict) for entry in payload):
        raise RuntimeError("Zotero item response must be an array of objects")
    items = [
        entry.get("data", entry) for entry in payload
        if isinstance(entry, dict)
        and isinstance(entry.get("data", entry), dict)
        and entry.get("data", entry).get("itemType") not in {"attachment", "note"}
    ]
    if keys:
        returned = [str(item.get("key", "")) for item in items]
        if len(returned) != len(set(returned)) or set(returned) != set(key_list):
            raise RuntimeError("Zotero response did not return every requested item key exactly once")
    return items


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--input", type=Path)
    source.add_argument("--stdin", action="store_true")
    source.add_argument("--keys")
    source.add_argument("--collection")
    parser.add_argument("--library", help="user:<id> or group:<id>")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    try:
        if args.input or args.stdin:
            items = load_input(args.input, args.stdin)
        else:
            items = fetch_zotero_items(args.library, args.keys, args.collection)
        results = [verify_item(item) for item in items]
        library = None
        if args.keys or args.collection:
            _, default_type, default_id = credentials()
            kind, library_id = parse_library(args.library, default_type, default_id)
            library = f"{kind}:{library_id}"
            for item, result in zip(items, results):
                result["stored_item"] = item
        summary: dict[str, int] = {}
        for result in results:
            summary[result["verdict"]] = summary.get(result["verdict"], 0) + 1
        output = {
            "schema_version": 1,
            "library": library,
            "source": "zotero" if library else "input",
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "results": results,
            "summary": summary,
        }
        rendered = json.dumps(output, indent=2, ensure_ascii=False) + "\n"
        if args.output:
            args.output.write_text(rendered, encoding="utf-8")
            print(args.output)
        else:
            sys.stdout.write(rendered)
        return 0 if all(result["verdict"] == "PASS" for result in results) else 1
    except (RuntimeError, OSError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
