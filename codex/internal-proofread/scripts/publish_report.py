#!/usr/bin/env python3
"""Publish the sole visible proofreading report with required Codex provenance."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from common import read_json, write_json


def parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def format_elapsed(seconds: int) -> str:
    hours, remainder = divmod(max(0, seconds), 3600)
    minutes, secs = divmod(remainder, 60)
    parts: list[str] = []
    if hours:
        parts.append(f"{hours}h")
    if hours or minutes:
        parts.append(f"{minutes}m")
    parts.append(f"{secs}s")
    return " ".join(parts)


CODEX_PROVENANCE_RE = re.compile(r"^> Created by: \*\*Codex\*\*  $", re.MULTILINE)


def codex_report_for(path: Path, original: Path) -> bool:
    """Return true only for a Codex report that identifies this exact draft."""
    if not path.is_file():
        return False
    try:
        header = "\n".join(path.read_text(encoding="utf-8-sig").splitlines()[:24])
    except (OSError, UnicodeError):
        return False
    expected_draft = f"Draft: `{original}`"
    return bool(CODEX_PROVENANCE_RE.search(header)) and expected_draft in header


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--model", required=True, help="exact Codex model label used for the run")
    accounting = parser.add_mutually_exclusive_group(required=True)
    accounting.add_argument("--tokens", type=int, help="aggregate runtime-reported token count")
    accounting.add_argument("--tokens-unavailable", action="store_true", help="runtime did not expose exact aggregate usage")
    parser.add_argument("--subagents", required=True, help="actual roles/counts, or none")
    parser.add_argument("--output", type=Path, help="visible Markdown destination")
    args = parser.parse_args()

    run_dir = args.run_dir.expanduser().resolve()
    manifest_path = run_dir / "run-manifest.json"
    report_path = run_dir / "report.md"
    if not manifest_path.is_file() or not report_path.is_file():
        parser.error(f"not an initialized proofread run: {run_dir}")
    model = args.model.strip()
    if not model:
        parser.error("--model must be a nonempty exact model label")
    if args.tokens is not None and args.tokens < 0:
        parser.error("--tokens must be nonnegative")

    if not args.subagents.strip() or "\n" in args.subagents or "\r" in args.subagents:
        parser.error("--subagents must be a nonempty single-line description")
    if "\n" in model or "\r" in model:
        parser.error("--model must be a single-line exact label")
    token_text = (
        "tokens unavailable (runtime did not expose exact usage)"
        if args.tokens_unavailable else f"{args.tokens:,} tokens"
    )

    scripts = Path(__file__).resolve().parent
    completed = subprocess.run(
        [sys.executable, str(scripts / "validate_run.py"), str(run_dir), "--require-ready"],
        text=True,
    )
    if completed.returncode:
        raise SystemExit(completed.returncode)

    manifest = read_json(manifest_path)
    original = Path(str(manifest["original_draft_path"])).expanduser().resolve()
    output = (
        args.output.expanduser().resolve()
        if args.output
        else original.with_name(f"{original.stem} — Proofread.md")
    )
    if output.exists() and not codex_report_for(output, original):
        if args.output:
            parser.error(
                f"refusing to overwrite a visible report not identified as Codex output: {output}; "
                "choose a different --output path"
            )
        output = original.with_name(f"{original.stem} — Codex Proofread.md")
        if output.exists() and not codex_report_for(output, original):
            parser.error(
                f"both default report paths are occupied by non-Codex files; choose --output: {output}"
            )
    generated = datetime.now().astimezone()
    started = parse_time(str(manifest["created_at"]))
    completed_at = generated.astimezone(timezone.utc)
    elapsed_seconds = int((completed_at.astimezone(timezone.utc) - started.astimezone(timezone.utc)).total_seconds())

    report_lines = report_path.read_text(encoding="utf-8").splitlines(keepends=True)
    visible_draft_line = f"Draft: `{manifest.get('original_draft_path', original)}`  \n"
    for index, line in enumerate(report_lines):
        if line.startswith("Draft: `"):
            report_lines[index] = visible_draft_line
            break
    report = "".join(report_lines)
    title, separator, body = report.partition("\n")
    if not separator:
        parser.error(f"canonical report has no title line: {report_path}")
    provenance = (
        f"{title}\n\n"
        f"> Created by: **Codex**  \n"
        f"> Model: `{model}`  \n"
        f"> Generated: {generated.strftime('%Y-%m-%d %H:%M:%S %Z')}  \n"
        f"> Elapsed: {format_elapsed(elapsed_seconds)}  \n"
        f"> Tokens: {token_text}\n\n"
    )
    published = provenance + body.lstrip("\n").rstrip() + (
        f"\n\n---\n\nTopic: Proofreading of {original.stem}\n"
        f"Date: {generated.strftime('%Y-%m-%d')}\n"
        f"By: Codex-{model}\n"
        f"Production details: {token_text}; elapsed through audit: {format_elapsed(elapsed_seconds)}; "
        f"subagents: {args.subagents.strip()}\n"
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    staged = run_dir / "published-report.tmp.md"
    staged.write_text(published, encoding="utf-8")
    try:
        os.replace(staged, output)
    except OSError:
        shutil.copy2(staged, output)
        staged.unlink()

    manifest["publication"] = {
        "visible_output_path": str(output),
        "created_by": "Codex",
        "model": model,
        "generated_at": generated.isoformat(timespec="seconds"),
        "run_completed_at": completed_at.isoformat(timespec="seconds"),
        "elapsed_seconds": elapsed_seconds,
        "tokens": args.tokens,
        "token_accounting": "unavailable" if args.tokens_unavailable else "runtime_reported",
        "subagents": args.subagents.strip(),
    }
    manifest["updated_at"] = generated.astimezone(timezone.utc).replace(microsecond=0).isoformat()
    write_json(manifest_path, manifest)
    print(str(output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
