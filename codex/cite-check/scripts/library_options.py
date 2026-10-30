"""Select from observed Zotero libraries without reading credentials or config files."""
from __future__ import annotations

import re


def normalize_libraries(value: list[dict] | None) -> list[dict] | None:
    if value is None:
        return None  # Unknown is distinct from a completed discovery with no libraries.
    if not isinstance(value, list):
        raise ValueError("libraries must be an array of public library records")
    result, ids = [], set()
    for row in value:
        if not isinstance(row, dict) or set(row) - {"id", "name", "status", "reason"}:
            raise ValueError("library records accept only id, name, status and reason; omit credentials/config")
        if any(not isinstance(row.get(k), str) or not row[k].strip() for k in ("id", "name", "status")):
            raise ValueError("library id, name and status must be nonempty strings")
        clean = {k: row[k].strip() for k in ("id", "name", "status")}
        if clean["id"] in ids:
            raise ValueError("library ids must be unique")
        if clean["status"] not in {"available", "unavailable"}:
            raise ValueError("library status must be available or unavailable")
        reason = row.get("reason", "")
        if not isinstance(reason, str) or (clean["status"] == "unavailable" and not reason.strip()):
            raise ValueError("an unavailable library needs a nonempty reason and access remedy")
        if reason.strip():
            clean["reason"] = reason.strip()
        ids.add(clean["id"])
        result.append(clean)
    return result


def words(value: str) -> set[str]:
    return {word for word in re.findall(r"[^\W_]+", value.casefold())
            if (len(word) >= 3 or any(c.isdigit() for c in word))
            and word not in {"the", "library", "zotero", "use", "please"}}


def match_library(value: str, libraries: list[dict]) -> dict:
    # Exact IDs take precedence; duplicate display names remain ambiguous.
    exact = [row for row in libraries if row["id"] == value.strip()]
    if not exact:
        exact = [row for row in libraries if row["name"].casefold() == value.strip().casefold()]
    tokens = words(value)
    matches = exact or [row for row in libraries if tokens and tokens.issubset(words(row["name"]))]
    if len(matches) != 1:
        raise ValueError("library description is ambiguous or unmatched; use an observed library id")
    if matches[0]["status"] != "available":
        raise ValueError(f"selected library is unavailable: {matches[0]['name']}; {matches[0]['reason']}")
    return matches[0]


def library_options(libraries: list[dict] | None, *, library: str | None = None,
                    no_zotero: bool = False, defaults: bool = False) -> tuple[dict, dict | None]:
    libraries = normalize_libraries(libraries)
    if type(no_zotero) is not bool or type(defaults) is not bool:
        raise ValueError("library skip/default flags must be booleans")
    if library is not None and (not isinstance(library, str) or not library.strip()):
        raise ValueError("library selection must be a nonempty id or description")
    if library is not None and no_zotero:
        raise ValueError("choose a library or no Zotero, not both")
    available = [row for row in libraries or [] if row["status"] == "available"]
    access = {"libraries": libraries, "requested": library, "skip": no_zotero, "defaults": defaults,
              "warnings": [f"{row['name']}: {row['reason']}" for row in libraries or []
                           if row["status"] == "unavailable"]}
    question = None
    selected = None
    if no_zotero:
        status = "skipped"
    elif library is not None:
        selected = match_library(library, libraries or [])
        status = "selected"
    elif libraries is None:
        status = "not_assessed"
    elif not available:
        status = "none_available"
    elif len(available) == 1:
        selected = available[0]
        status = "selected"
    elif defaults:
        status = "skipped"
        access["warnings"].append("Multiple Zotero libraries are available; none selected in defaults mode.")
    else:
        status = "needs_choice"
        # Keep within three options; every other library is selectable by free text.
        names = "; ".join(f"{row['name']} [{row['id']}]" for row in available)
        options = [{"label": row["name"], "value": row["id"], "description": f"Search {row['name']} ({row['id']}) first."}
                   for row in available[:2]]
        options.append({"label": "No Zotero this run", "value": "no_zotero",
                        "description": "Use supplied files and authoritative web sources."})
        question = {"id": "library", "title": f"Which Zotero library should I search? Available: {names}. You can type any listed name or id.",
                    "options": options}
    access["selection"] = {"status": status}
    if selected:
        access["selection"].update({"id": selected["id"], "name": selected["name"]})
    return access, question


def validate_library_access(access: dict) -> None:
    if not isinstance(access, dict) or not {"libraries", "requested", "skip", "defaults"}.issubset(access):
        raise ValueError("invalid library access record")
    expected, question = library_options(access["libraries"], library=access["requested"],
                                         no_zotero=access["skip"], defaults=access["defaults"])
    if access != expected or question is not None:
        raise ValueError("library selection must be resolved and match its observed inventory")
