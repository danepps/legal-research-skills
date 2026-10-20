#!/usr/bin/env python3
"""Attach verified PDF bytes to an existing Zotero item via Web API v3."""

from __future__ import annotations

import argparse
import hashlib
import html
import io
import json
import mimetypes
import os
import re
import subprocess
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any


API = "https://api.zotero.org"
UA = "build-zotero-library-pdf-attach/1.0"
KEYCHAIN_SERVICE = "codex-zotero-mcp"
MAX_FILENAME_BYTES = 180
INVALID_FILENAME_CHARS = re.compile(r'[\x00-\x1f\x7f/\\:*?"<>|]+')
YEAR = re.compile(r"(?<!\d)(1[0-9]{3}|2[0-9]{3})(?!\d)")


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def keychain_value(account: str) -> str | None:
    try:
        result = subprocess.run(
            ["/usr/bin/security", "find-generic-password", "-s", KEYCHAIN_SERVICE,
             "-a", account, "-w"],
            check=True, capture_output=True, text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip() or None


def credentials() -> tuple[str, str, str]:
    key = os.environ.get("ZOTERO_API_KEY") or keychain_value("api-key")
    library_id = os.environ.get("ZOTERO_LIBRARY_ID") or keychain_value("library-id") or ""
    library_type = os.environ.get("ZOTERO_LIBRARY_TYPE", "user")
    if not key:
        raise RuntimeError("no Zotero API key; set ZOTERO_API_KEY or configure codex-zotero-mcp in Keychain")
    return key, library_type, library_id


def parse_library(value: str | None, default_type: str, default_id: str) -> tuple[str, str]:
    raw = value or f"{default_type}:{default_id}"
    try:
        kind, library_id = raw.split(":", 1)
    except ValueError as exc:
        raise RuntimeError("library must be user:<id> or group:<id>") from exc
    if kind not in {"user", "group"} or not library_id:
        raise RuntimeError("library must be user:<id> or group:<id>")
    return kind, library_id


def library_base(kind: str, library_id: str) -> str:
    return f"/{kind}s/{urllib.parse.quote(library_id, safe='')}"


def api_request(
    path: str,
    key: str,
    method: str = "GET",
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, Any, dict[str, str]]:
    request_headers = {
        "User-Agent": UA,
        "Zotero-API-Key": key,
        "Zotero-API-Version": "3",
        "Accept": "application/json",
    }
    request_headers.update(headers or {})
    request = urllib.request.Request(API + path, data=data, headers=request_headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            raw = response.read()
            value = json.loads(raw) if raw else None
            return response.status, value, dict(response.headers.items())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:1500]
        raise RuntimeError(f"Zotero API {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Zotero API network error: {exc.reason}") from exc


def fetch_pdf(url: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": UA, "Accept": "application/pdf,*/*"},
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            return response.read()
    except urllib.error.URLError as exc:
        raise RuntimeError(f"PDF fetch failed: {exc.reason}") from exc


def digest(body: bytes, algorithm: str) -> str:
    return hashlib.new(algorithm, body).hexdigest()


def validate_pdf(body: bytes) -> dict[str, Any]:
    """Parse the page tree before calling bytes a structurally verified PDF."""
    if not body.startswith(b"%PDF-"):
        raise RuntimeError("source bytes are not a PDF; likely a login or bot-wall page")
    try:
        from pypdf import PdfReader
        parser = "pypdf"
    except ImportError:
        try:
            from PyPDF2 import PdfReader
            parser = "PyPDF2"
        except ImportError as exc:
            raise RuntimeError("PDF structural verification requires pypdf or PyPDF2; attachment not verified") from exc
    try:
        reader = PdfReader(io.BytesIO(body), strict=True)
        if reader.is_encrypted and not reader.decrypt(""):
            raise ValueError("PDF is encrypted and cannot be inspected")
        count = len(reader.pages)
        if count < 1:
            raise ValueError("PDF has no pages")
        for page in reader.pages:
            _ = page.mediabox
            contents = page.get_contents()
            if contents is not None:
                contents.get_data()
    except Exception as exc:
        raise RuntimeError(f"PDF structural verification failed: {exc}") from exc
    return {"status": "parsed", "parser": parser, "page_count": count}


def append_ledger(path: Path, result: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(result, ensure_ascii=False) + "\n")


def emit_result(result: dict[str, Any], output: Path | None, ledger: Path | None) -> int:
    rendered = json.dumps(result, indent=2) + "\n"
    if output:
        output.write_text(rendered, encoding="utf-8")
        print(output)
    else:
        sys.stdout.write(rendered)
    if ledger:
        append_ledger(ledger, result)
    return 0 if result.get("status") == "VERIFIED" else 1


def fetch_stored_file(path: str, key: str) -> bytes:
    request = urllib.request.Request(
        API + path,
        headers={
            "User-Agent": UA,
            "Zotero-API-Key": key,
            "Zotero-API-Version": "3",
            "Accept": "application/pdf,*/*",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            return response.read()
    except urllib.error.URLError as exc:
        raise RuntimeError(f"could not fetch stored Zotero attachment: {exc.reason}") from exc


def successful_key(response: Any) -> str:
    if not isinstance(response, dict):
        return ""
    mapping = response.get("successful") or response.get("success") or {}
    value = mapping.get("0") if isinstance(mapping, dict) else None
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        if value.get("key"):
            return str(value["key"])
        if isinstance(value.get("data"), dict) and value["data"].get("key"):
            return str(value["data"]["key"])
    return ""


def clean_text(value: Any) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", "", str(value or "")))
    return " ".join(unicodedata.normalize("NFC", text).split())


def safe_filename_part(value: Any) -> str:
    text = INVALID_FILENAME_CHARS.sub(" ", clean_text(value))
    return re.sub(r"\s+", " ", text).strip(" .-_")


def creator_filename_part(item: dict[str, Any]) -> str:
    creators = item.get("creators")
    if not isinstance(creators, list):
        return ""
    ranked: list[tuple[int, str]] = []
    for creator in creators:
        if not isinstance(creator, dict):
            continue
        name = safe_filename_part(creator.get("lastName") or creator.get("name"))
        if not name:
            continue
        creator_type = str(creator.get("creatorType", ""))
        if creator_type in {"author", "bookAuthor"}:
            rank = 0
        elif creator_type == "editor":
            rank = 1
        elif creator_type in {"contributor", "translator", "seriesEditor"}:
            rank = 3
        else:
            rank = 2
        ranked.append((rank, name))
    if not ranked:
        return ""
    best_rank = min(rank for rank, _ in ranked)
    names = [name for rank, name in ranked if rank == best_rank]
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]} & {names[1]}"
    return f"{names[0]} et al."


def truncate_utf8(value: str, byte_limit: int) -> str:
    encoded = value.encode("utf-8")
    if len(encoded) <= byte_limit:
        return value
    return encoded[:byte_limit].decode("utf-8", errors="ignore").rstrip(" .-_")


def normalize_pdf_filename(value: str, max_bytes: int = MAX_FILENAME_BYTES) -> str:
    raw = clean_text(value)
    if raw.lower().endswith(".pdf"):
        raw = raw[:-4]
    stem = safe_filename_part(raw) or "attachment"
    stem = truncate_utf8(stem, max_bytes - len(".pdf"))
    return f"{stem}.pdf"


def attachment_filename(item: dict[str, Any], fallback: str) -> str:
    creator = creator_filename_part(item)
    date = clean_text(item.get("date"))
    year_match = YEAR.search(date)
    year = year_match.group(1) if year_match else ""
    title = safe_filename_part(item.get("title"))
    parts = [part for part in (creator, year, title) if part]
    return normalize_pdf_filename(" - ".join(parts) if parts else fallback)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--item", required=True, help="existing parent item key")
    parser.add_argument("--library", help="user:<id> or group:<id>")
    sources = parser.add_mutually_exclusive_group(required=True)
    sources.add_argument("--url", help="direct, authorized PDF URL")
    sources.add_argument("--file", type=Path, help="local PDF (for example, one the user downloaded from an authenticated source)")
    sources.add_argument("--verify-existing", action="store_true", help="verify an existing stored PDF child")
    parser.add_argument("--attachment-key", help="specific existing attachment key")
    parser.add_argument("--source-url", default="", help="provenance URL when using --file")
    parser.add_argument(
        "--source-mode",
        choices=("url", "file"),
    )
    parser.add_argument("--title", default="Full Text PDF")
    parser.add_argument(
        "--filename",
        help="explicit stored filename; defaults to Creator - Year - Title.pdf from the parent item",
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--ledger", type=Path)
    args = parser.parse_args()

    try:
        key, default_type, default_id = credentials()
        kind, library_id = parse_library(args.library, default_type, default_id)
        base = library_base(kind, library_id)
        if args.verify_existing:
            parent = urllib.parse.quote(args.item, safe="")
            _, children, _ = api_request(f"{base}/items/{parent}/children?format=json", key)
            if not isinstance(children, list):
                raise RuntimeError("Zotero child-item response is malformed")
            matches = []
            for child in children:
                data = child.get("data", child) if isinstance(child, dict) else {}
                child_key = child.get("key") if isinstance(child, dict) else ""
                child_key = child_key or data.get("key")
                if (
                    data.get("itemType") == "attachment"
                    and data.get("contentType") == "application/pdf"
                    and child_key
                    and (not args.attachment_key or child_key == args.attachment_key)
                ):
                    matches.append((str(child_key), data))
            if not matches:
                raise RuntimeError("no matching PDF attachment child exists in Zotero")
            attachment_key, metadata = matches[0]
            stored_path = f"{base}/items/{urllib.parse.quote(attachment_key, safe='')}/file"
            body = fetch_stored_file(stored_path, key)
            pdf_validation = validate_pdf(body)
            md5 = digest(body, "md5")
            recorded_md5 = str(metadata.get("md5", ""))
            verified = bool(recorded_md5) and recorded_md5 == md5 and metadata.get("parentItem") == args.item
            result = {
                "schema_version": 1,
                "status": "VERIFIED" if verified else "UNVERIFIED",
                "library": f"{kind}:{library_id}",
                "parent_item_key": args.item,
                "attachment_item_key": attachment_key,
                "filename": metadata.get("filename") or f"{attachment_key}.pdf",
                "content_type": "application/pdf",
                "size": len(body),
                "pdf_validation": pdf_validation,
                "md5": md5,
                "sha256": digest(body, "sha256"),
                "source_url": args.source_url,
                "source_mode": "existing",
                "verified_at": now(),
            }
            return emit_result(result, args.output, args.ledger)
        source_url = args.url or args.source_url
        if args.url:
            body = fetch_pdf(args.url)
            guessed = Path(urllib.parse.urlparse(args.url).path).name or "attachment.pdf"
            source_mode = args.source_mode or "url"
        else:
            source_path = args.file.expanduser().resolve()
            body = source_path.read_bytes()
            guessed = source_path.name
            source_mode = args.source_mode or "file"
        pdf_validation = validate_pdf(body)
        parent_key = urllib.parse.quote(args.item, safe="")
        _, parent_response, _ = api_request(f"{base}/items/{parent_key}", key)
        parent_metadata = (
            parent_response.get("data", parent_response)
            if isinstance(parent_response, dict)
            else {}
        )
        if not isinstance(parent_metadata, dict) or parent_metadata.get("itemType") in {
            "attachment", "note"
        }:
            raise RuntimeError("parent Zotero item metadata is malformed or is not a bibliographic item")
        filename = (
            normalize_pdf_filename(args.filename)
            if args.filename
            else attachment_filename(parent_metadata, guessed)
        )
        content_type = mimetypes.guess_type(filename)[0] or "application/pdf"
        if content_type != "application/pdf":
            content_type = "application/pdf"
        md5 = digest(body, "md5")
        sha256 = digest(body, "sha256")
        size = len(body)
        attachment = [{
            "itemType": "attachment",
            "parentItem": args.item,
            "linkMode": "imported_file",
            "title": args.title,
            "contentType": "application/pdf",
            "filename": filename,
            "charset": "",
        }]
        payload = json.dumps(attachment, separators=(",", ":")).encode("utf-8")
        _, created, _ = api_request(
            f"{base}/items", key, "POST", payload,
            {"Content-Type": "application/json"},
        )
        attachment_key = successful_key(created)
        if not attachment_key:
            raise RuntimeError(f"could not create Zotero attachment item: {created}")

        encoded = urllib.parse.urlencode({
            "md5": md5,
            "filename": filename,
            "filesize": size,
            "mtime": int(time.time() * 1000),
        }).encode("utf-8")
        item_path = f"{base}/items/{urllib.parse.quote(attachment_key, safe='')}/file"
        _, authorization, _ = api_request(
            item_path, key, "POST", encoded,
            {"Content-Type": "application/x-www-form-urlencoded", "If-None-Match": "*"},
        )
        if not isinstance(authorization, dict):
            raise RuntimeError("Zotero upload authorization response is malformed")
        if not authorization.get("exists"):
            upload = authorization.get("prefix", "").encode() + body + authorization.get("suffix", "").encode()
            upload_request = urllib.request.Request(
                str(authorization["url"]), data=upload,
                headers={"Content-Type": str(authorization["contentType"])}, method="POST",
            )
            with urllib.request.urlopen(upload_request, timeout=300) as response:
                if response.status not in {200, 201, 204}:
                    raise RuntimeError(f"Zotero storage upload returned {response.status}")
            register = urllib.parse.urlencode({"upload": authorization["uploadKey"]}).encode("utf-8")
            api_request(
                item_path, key, "POST", register,
                {"Content-Type": "application/x-www-form-urlencoded", "If-None-Match": "*"},
            )

        metadata: dict[str, Any] = {}
        for _ in range(4):
            _, fetched, _ = api_request(f"{base}/items/{urllib.parse.quote(attachment_key, safe='')}", key)
            metadata = fetched.get("data", fetched) if isinstance(fetched, dict) else {}
            if metadata.get("md5") == md5:
                break
            time.sleep(0.5)
        verified = (
            metadata.get("itemType") == "attachment"
            and metadata.get("parentItem") == args.item
            and metadata.get("contentType") == "application/pdf"
            and metadata.get("filename") == filename
            and metadata.get("md5") == md5
        )
        result = {
            "schema_version": 1,
            "status": "VERIFIED" if verified else "UNVERIFIED",
            "library": f"{kind}:{library_id}",
            "parent_item_key": args.item,
            "attachment_item_key": attachment_key,
            "filename": filename,
            "content_type": "application/pdf",
            "size": size,
            "pdf_validation": pdf_validation,
            "md5": md5,
            "sha256": sha256,
            "source_url": source_url,
            "source_mode": source_mode,
            "verified_at": now(),
        }
        return emit_result(result, args.output, args.ledger)
    except (RuntimeError, OSError, KeyError, urllib.error.URLError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
