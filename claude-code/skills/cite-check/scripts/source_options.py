#!/usr/bin/env python3
"""Offline source-choice planning and explicit project persistence. Stdlib only.

Independent public-plugin copy; no imports from the other plugin tree.
Preview never creates a folder or edits project instructions. Apply only after
the source choice is returned; remembering also needs the offered save accepted.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

PROJECT_FILE = "CLAUDE.md"
DEFAULT_RELATIVE = Path(".config/legal-research/source-folder")


def default_file():
    return Path.home() / DEFAULT_RELATIVE


def project_values(project, key, preferred=PROJECT_FILE):
    for filename in (preferred, "CLAUDE.md" if preferred == "AGENTS.md" else "AGENTS.md"):
        path = Path(project).expanduser() / filename
        if path.is_file():
            values = re.findall(r"^" + re.escape(key) + r":[ \t]*(.*\S)[ \t]*$",
                                path.read_text(encoding="utf-8"), re.M | re.I)
            if values:
                return [v.strip().strip('`"\'') for v in values]
    return []


def discover_folders(draft=None, project=None, folders=(), *, config=None):
    """Request > native project line (fallback other file) > Sources > default.

    Project 'none' suppresses all fallback. An explicit request can override it.
    'none' origin denotes unsettled; 'project_none' denotes an affirmative skip.
    """
    base = Path(project or (Path(draft).expanduser().resolve().parent if draft else Path.cwd())).expanduser().resolve()
    names, origin = list(map(str, folders)), "request"
    if not names:
        names, origin = project_values(base, "Source folder"), "project"
        if any(n.casefold() == "none" for n in names):
            return [], "project_none"
    if not names and draft:
        origin = "beside_draft"
        names = [str(p) for p in sorted(Path(draft).expanduser().resolve().parent.iterdir())
                 if p.is_dir() and p.name.casefold() == "sources"]
    if not names:
        config = Path(config) if config is not None else default_file()
        if config.is_file():
            value = config.read_text(encoding="utf-8").strip()
            if not value or len(value.splitlines()) != 1 or not Path(value).expanduser().is_absolute():
                raise ValueError("saved source-folder setting must contain one absolute folder path")
            names, origin = [value], "default"
    paths = []
    for name in names:
        if not name.strip() or "\n" in name or "\r" in name:
            raise ValueError("source folder must be one nonempty path")
        path = (base / Path(name.strip().strip('`"\'')).expanduser()).resolve()
        if path not in paths:
            paths.append(path)
    return paths, origin if paths else "none"


def normalize_libraries(libraries):
    if libraries is None:
        return None
    if not isinstance(libraries, list):
        raise ValueError("libraries must be public metadata records")
    result = []
    for row in libraries:
        if not isinstance(row, dict):
            raise ValueError("invalid library record")
        if "server" in row:
            if set(row) - {"server", "type", "id", "name", "description", "label"}:
                raise ValueError("omit credentials and raw configuration")
            row = {"id": row["server"], "name": row.get("label") or row["name"],
                   "status": "available", "description": row.get("description", "")}
        if set(row) - {"id", "name", "status", "reason", "description"}:
            raise ValueError("omit credentials and raw configuration")
        if any(not isinstance(row.get(k), str) or not row[k].strip() for k in ("id", "name", "status")):
            raise ValueError("library id/name/status must be nonempty strings")
        if row["status"] not in {"available", "unavailable"}:
            raise ValueError("invalid library status")
        result.append(dict(row))
    if len({r["id"] for r in result}) != len(result):
        raise ValueError("duplicate library IDs")
    return result


def match_library(value, libraries):
    available = libraries or []
    exact = [r for r in available if value.strip() == r["id"]]
    if not exact:
        exact = [r for r in available if value.strip().casefold() == r["name"].casefold()]
    if not exact:
        tokens = {w for w in re.findall(r"[^\W_]+", value.casefold())
                  if (len(w) >= 3 or any(c.isdigit() for c in w)) and w not in
                  {"the", "library", "zotero", "use", "please", "my", "with", "one", "for"}}
        exact = [r for r in available if tokens and tokens <= set(re.findall(
            r"[^\W_]+", (r["name"] + " " + r.get("description", "") + " " + r["id"]).casefold()))]
    if len(exact) != 1:
        raise ValueError("library description is ambiguous or unmatched; use a listed name or ID")
    if exact[0]["status"] != "available":
        raise ValueError("selected library is unavailable: " + exact[0]["name"])
    return exact[0]


def resolve(inputs):
    """Resolve the two halves independently; answers affect only offered halves."""
    if any(type(inputs.get(k)) is not bool for k in ("headless", "no_zotero")):
        raise ValueError("source-choice flags must be booleans")
    paths = list(inputs["discovery"]["paths"])
    origin = inputs["discovery"]["origin"]
    libraries = normalize_libraries(inputs["libraries"])
    available = [r for r in libraries or [] if r["status"] == "available"]
    library, skip = inputs["library"], inputs["no_zotero"]
    if library and skip:
        raise ValueError("choose a library or no Zotero, not both")
    warnings = []
    saved = inputs["project_library"]
    if not library and not skip and saved:
        if saved.casefold() == "none":
            skip = True
        else:
            try:
                library = match_library(saved, libraries)["id"]
            except ValueError as exc:
                warnings.append(f"Saved Zotero library cannot be used: {saved}; {exc}.")
    folder_open = origin == "none"
    # A sole library remains the automatic choice with an already settled folder;
    # with both halves open offer the four simple source modes.
    library_open = not library and not skip and bool(available) and (len(available) > 1 or folder_open)
    scope = [k for k, is_open in (("folder", folder_open), ("library", library_open)) if is_open]
    selected = match_library(library, libraries) if library else None
    if not available and not selected:
        skip = True
    if not folder_open and not selected and not skip and len(available) == 1:
        selected = available[0]
        scope = [k for k in scope if k != "library"]
    choices = inputs["choices"]
    if choices is not None and (not choices or len(choices) != len(set(choices))):
        raise ValueError("source choices must be nonempty and unique")
    create = False
    question = None
    if choices:
        choices = list(choices)
        if choices == ["both"]:
            if len(available) != 1 or scope != ["folder", "library"]:
                raise ValueError("Both requires one offered library and an unsettled folder")
            choices = ["folder", "library:" + available[0]["id"]]
        if "web" in choices and choices != ["web"]:
            raise ValueError("Neither cannot be combined with another choice")
        named = [c[8:] for c in choices if c.startswith("library:")]
        if len(named) > 1 or any(c not in {"web", "folder"} and not c.startswith("library:") for c in choices):
            raise ValueError("choose at most one named library, optionally with Folder")
        if named:
            if inputs["no_zotero"] or (inputs["library"] and match_library(inputs["library"], libraries)["id"] != named[0]):
                raise ValueError("conflicting library choices")
            selected = match_library(named[0], libraries)
            skip = False
        elif "library" in scope:
            selected, skip = None, True
        if "folder" in choices:
            if not paths:
                paths, create = [inputs["new_folder"]], True
            origin = "choice"
        elif "folder" in scope:
            paths, origin = [], "choice_none"
    elif scope and not inputs["headless"]:
        options = []
        if "library" in scope:
            capacity = 2 if "folder" in scope else 3
            for row in available[:capacity]:
                options.append({"label": row["name"], "value": "library:" + row["id"], "description": "Use this Zotero library."})
        else:
            capacity = 0
        if "folder" in scope:
            options.append({"label": "Folder of PDFs", "value": "folder", "description": "Use Sources beside the draft; no path entry needed."})
            if "library" in scope and len(available) == 1:
                options.append({"label": "Both", "value": "both", "description": "Use the library and a folder of PDFs."})
        options.append({"label": "Neither — web only" if len(scope)==2 or not selected and not paths else
                       "No folder" if scope==["folder"] else "No Zotero", "value": "web",
                        "description": "Check sources on the web only." if len(scope)==2 or not selected and not paths else
                                       "Do not look for my own copies." if scope==["folder"] else "Do not search Zotero."})
        question = {"id": "sources", "multiSelect": len(available)>=2 and len(scope)==2,  # one library is one choice; only library-plus-folder needs two
                    "title": "Which source copies should I use?" if len(scope)==2 else
                             "Which Zotero library should I use?" if scope==["library"] else "Should I use a folder of PDFs?",
                    "save_offer": "I can remember this choice for the project; say 'this run only' to decline.", "options": options}
        if "library" in scope and len(available)>capacity:
            question["library_list"] = "; ".join(f"{r['name']} [{r['id']}]" for r in available)
    elif inputs["headless"]:
        if folder_open:
            origin = "headless_skip"
        if not selected and not skip:
            if len(available)==1:
                selected = available[0]
            elif len(available)>1:
                skip = True
                warnings.append("Multiple Zotero libraries remain unchosen; skipping Zotero in this headless run.")
    if skip:
        selected = None
    return {"status": "needs_choice" if question else "ready", "question": question,
            "choice_scope": scope, "folder_paths": paths, "folder_origin": origin, "create_folder": create,
            "library_id": selected["id"] if selected else None,
            "library_name": selected["name"] if selected else None,
            "skip_zotero": skip, "warnings": warnings}


def plan_sources(draft, *, project=None, folders=(), libraries=None, library=None,
                 no_zotero=False, choices=None, headless=False, config=None):
    libraries = normalize_libraries(libraries)
    draft = Path(draft).expanduser().resolve()
    project = Path(project or draft.parent).expanduser().resolve()
    paths, origin = discover_folders(draft, project, folders, config=config)
    saved = project_values(project, "Zotero library")
    if len(set(saved)) > 1:
        raise ValueError("conflicting project Zotero library lines")
    saved = saved[0] if saved else None
    if saved and "→" in saved:
        saved = re.sub(r"^(?:MCP server|ID)\s+", "", saved.split("→", 1)[1].strip())
    inputs = {"discovery": {"paths": list(map(str, paths)), "origin": origin},
              "libraries": libraries, "library": library, "no_zotero": no_zotero,
              "choices": choices, "headless": headless, "project_library": saved,
              "project": str(project), "project_file": PROJECT_FILE,
              "new_folder": str(draft.parent / "Sources")}
    return {"schema_version": 1, "inputs": inputs, **resolve(inputs)}


def validate_plan(plan):
    if not isinstance(plan, dict) or plan.get("schema_version") != 1:
        raise ValueError("invalid source-choice plan")
    expected = {"schema_version": 1, "inputs": plan["inputs"], **resolve(plan["inputs"])}
    if plan != expected or plan["status"] != "ready":
        raise ValueError("source choices must be resolved and match the frozen preview")
    if any(not Path(p).is_absolute() for p in plan["folder_paths"]):
        raise ValueError("source choices require absolute folder paths")


def materialize(plan, *, remember=False):
    validate_plan(plan)
    if remember and not plan["inputs"]["choices"]:
        raise ValueError("remembering needs an answered source question, not a silent/default choice")
    if plan["create_folder"]:
        target = Path(plan["inputs"]["new_folder"])
        if plan["folder_paths"] != [str(target)] or target.is_symlink():
            raise ValueError("refusing to create an unexpected source folder")
        target.mkdir(exist_ok=True)
    if not remember:
        return
    target = Path(plan["inputs"]["project"]) / plan["inputs"]["project_file"]
    if target.name not in {"AGENTS.md", "CLAUDE.md"} or target.is_symlink():
        raise ValueError("refusing unexpected project instruction target")
    original = target.read_text(encoding="utf-8") if target.exists() else ""
    folder_lines = ["Source folder: " + p for p in plan["folder_paths"]] or ["Source folder: none"]
    lib_line = (f"Zotero library: {plan['library_name']} → " +
                ("MCP server " if target.name == "CLAUDE.md" else "ID ") + plan["library_id"]
                if plan["library_id"] else "Zotero library: none")
    # Save only the offered/answered settings. A folder answer cannot erase a
    # previously saved library that was not offered in the same question.
    choices = plan["inputs"]["choices"]
    keys, lines = [], []
    if "folder" in plan["choice_scope"] or "folder" in choices:
        keys.append("Source folder"); lines.extend(folder_lines)
    if "library" in plan["choice_scope"] or any(c.startswith("library:") for c in choices):
        keys.append("Zotero library"); lines.append(lib_line)
    if not keys:
        return
    text = re.sub(r"^(?:" + "|".join(keys) + r"):[^\r\n]*(?:\r?\n|$)", "", original, flags=re.M | re.I)
    text = text + ("\n" if text and not text.endswith("\n") else "") + "\n".join(lines) + "\n"
    target.write_text(text, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("draft", type=Path)
    parser.add_argument("--project", type=Path)
    parser.add_argument("--folder", action="append", default=[])
    parser.add_argument("--libraries", type=Path, help="public id/name/status inventory; no credentials")
    parser.add_argument("--library")
    parser.add_argument("--no-zotero", action="store_true")
    parser.add_argument("--choose", action="append")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--remember", action="store_true")
    args = parser.parse_args()
    try:
        libs = json.loads(args.libraries.read_text(encoding="utf-8")) if args.libraries else None
        plan = plan_sources(args.draft, project=args.project, folders=args.folder, libraries=libs,
                            library=args.library, no_zotero=args.no_zotero, choices=args.choose, headless=args.headless)
        if args.remember and not args.apply:
            raise ValueError("--remember needs --apply after the save offer was accepted")
        if args.apply:
            materialize(plan, remember=args.remember)
        print(json.dumps(plan, ensure_ascii=False, indent=2))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
