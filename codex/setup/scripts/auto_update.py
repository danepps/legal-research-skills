#!/usr/bin/env python3
"""Opt-in, per-user updates of the legal-research Codex marketplace plugin.

No third-party dependencies. The scheduler runs a durable copy of this script,
never a path inside Codex's replaceable plugin cache. It invokes only Codex's
plugin manager, and never installs a missing or disabled plugin.
"""
from __future__ import annotations

import argparse
import csv
from contextlib import contextmanager
from datetime import datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import platform
import plistlib
import shutil
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET

OWNER = "danepps/legal-research-skills:codex-updater-v1"
MARKETPLACE = "danepps-legal-research-codex"
PLUGIN = "legal-research@" + MARKETPLACE
REPOSITORY = "https://github.com/danepps/legal-research-skills.git"
DAY = 86400


class UpdateError(Exception):
    pass


def absolute(path):
    # Keep executable symlinks: resolving one can pin a versioned installation.
    return Path(os.path.abspath(os.path.expanduser(str(path))))


def atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".updater-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data if isinstance(data, bytes) else data.encode("utf-8"))
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_json(path, default=None):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise UpdateError(f"Cannot read {path}: {exc}") from exc


def write_json(path, value):
    atomic_write(path, json.dumps(value, indent=2) + "\n")


@contextmanager
def lock(root):
    root.mkdir(parents=True, exist_ok=True)
    with (root / "lock").open("a+b") as stream:
        try:
            if os.name == "nt":
                import msvcrt
                stream.seek(0)
                if not stream.read(1):
                    stream.write(b"0"); stream.flush()
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise UpdateError("Another updater operation is running; retry after it finishes.") from exc
        try:
            yield
        finally:
            if os.name == "nt":
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def execute(args, *, env=None, cwd=None, check=True, timeout=60):
    try:
        result = subprocess.run(args, env=env, cwd=cwd, text=True,
                                capture_output=True, stdin=subprocess.DEVNULL,
                                timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise UpdateError(f"Could not run {Path(args[0]).name}: {exc}") from exc
    if check and result.returncode:
        detail = (result.stderr or result.stdout).strip()[-3000:]
        raise UpdateError(f"{Path(args[0]).name} exited {result.returncode}: {detail}")
    return result


def codex(config, args, *, as_json=False):
    env = {**os.environ, "CODEX_HOME": config["codex_home"],
           "PATH": config["path"], "GIT_TERMINAL_PROMPT": "0"}
    result = execute([config["codex"], *args], env=env,
                     cwd=config["state_dir"], timeout=300)
    if not as_json:
        return result.stdout
    try:
        return json.loads(result.stdout)
    except ValueError as exc:
        raise UpdateError("Codex returned invalid JSON; update the CLI and retry setup.") from exc


def installed_plugin(config):
    data = codex(config, ["plugin", "list", "--marketplace", MARKETPLACE, "--json"], as_json=True)
    if not isinstance(data, dict) or not isinstance(data.get("installed"), list):
        raise UpdateError("Unrecognized Codex plugin listing; no update attempted.")
    matches = [row for row in data["installed"]
               if isinstance(row, dict) and row.get("pluginId") == PLUGIN]
    if not matches:
        return None
    if len(matches) != 1 or matches[0].get("installed") is not True:
        raise UpdateError("Ambiguous installed-plugin state; no update attempted.")
    return matches[0]


def verify_source(plugin):
    source = plugin.get("marketplaceSource", {})
    # Deliberately reject local checkouts, forks, and pinned refs/SHAs. This updater
    # follows this repository's default branch, not arbitrary marketplace names.
    if source not in ({"sourceType": "git", "source": REPOSITORY},
                      {"sourceType": "git", "source": REPOSITORY.removesuffix(".git")}):
        raise UpdateError("Automatic updates require the unpinned official GitHub marketplace. "
                          "Local checkouts, forks, and pinned sources are left unchanged.")


def load_config(root):
    config = read_json(root / "config.json")
    if config is not None and (not isinstance(config, dict) or config.get("owner") != OWNER
                               or config.get("state_dir") != str(root)):
        raise UpdateError("Updater directory has an unrecognized configuration; left unchanged.")
    return config


def unit_quote(value):
    # systemd performs specifier and environment expansion even inside quotes.
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%").replace("$", "$$") + '"'


def scheduler_files(config):
    root = Path(config["state_dir"])
    args = [config["python"], str(root / "auto_update.py"), "--state-dir", str(root), "run"]
    name = config["job_name"]
    if config["system"] == "Darwin":
        return {Path(config["scheduler_dir"]) / (name + ".plist"): plistlib.dumps({
            "Label": name, "ProgramArguments": args, "RunAtLoad": True,
            "StartInterval": 3600, "ProcessType": "Background",
            "WorkingDirectory": str(root),
        })}
    if config["system"] == "Linux":
        folder = Path(config["scheduler_dir"])
        service = ("# " + OWNER + "\n[Unit]\nDescription=Legal Research Codex updates\n"
                   "[Service]\nType=oneshot\nExecStart=" + " ".join(map(unit_quote, args)) +
                   "\nTimeoutStartSec=20min\n")
        timer = ("# " + OWNER + "\n[Unit]\nDescription=Check Legal Research Codex update schedule\n"
                 "[Timer]\nOnCalendar=hourly\nPersistent=true\n"
                 "[Install]\nWantedBy=timers.target\n")
        return {folder / (name + ".service"): service.encode(),
                folder / (name + ".timer"): timer.encode()}
    if config["system"] == "Windows":
        task = ET.Element("Task", version="1.2", xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task")
        registration = ET.SubElement(task, "RegistrationInfo")
        ET.SubElement(registration, "Description").text = OWNER
        trigger = ET.SubElement(ET.SubElement(task, "Triggers"), "TimeTrigger")
        repetition = ET.SubElement(trigger, "Repetition")
        ET.SubElement(repetition, "Interval").text = "PT1H"
        ET.SubElement(repetition, "StopAtDurationEnd").text = "false"
        ET.SubElement(trigger, "StartBoundary").text = (datetime.now() + timedelta(minutes=1)).isoformat(timespec="seconds")
        ET.SubElement(trigger, "Enabled").text = "true"
        principal = ET.SubElement(ET.SubElement(task, "Principals"), "Principal", id="Author")
        ET.SubElement(principal, "UserId").text = config["windows_user"]
        ET.SubElement(principal, "LogonType").text = "InteractiveToken"
        ET.SubElement(principal, "RunLevel").text = "LeastPrivilege"
        settings = ET.SubElement(task, "Settings")
        for key, value in (("MultipleInstancesPolicy", "IgnoreNew"),
                           ("DisallowStartIfOnBatteries", "false"),
                           ("StopIfGoingOnBatteries", "false"),
                           ("StartWhenAvailable", "true"), ("Enabled", "true"),
                           ("ExecutionTimeLimit", "PT20M")):
            ET.SubElement(settings, key).text = value
        action = ET.SubElement(ET.SubElement(task, "Actions", Context="Author"), "Exec")
        ET.SubElement(action, "Command").text = args[0]
        ET.SubElement(action, "Arguments").text = subprocess.list2cmdline(args[1:])
        ET.SubElement(action, "WorkingDirectory").text = str(root)
        return {root / "task.xml": ET.tostring(task, encoding="utf-16", xml_declaration=True)}
    raise UpdateError("Automatic scheduling supports macOS, Linux with systemd, and Windows.")


def job_exists(config):
    system, name = config["system"], config["job_name"]
    if system == "Darwin":
        result = execute(["launchctl", "print", f"gui/{os.getuid()}/{name}"], check=False)
        if result.returncode == 0:
            return True
        detail = result.stderr or result.stdout
        if "Could not find service" in detail or "Could not find specified service" in detail:
            return False
        raise UpdateError("Could not inspect launchd job: " + detail.strip()[-1500:])
    if system == "Linux":
        result = execute(["systemctl", "--user", "show", name + ".timer", "--property=LoadState", "--value"])
        value = result.stdout.strip()
        if value not in ("loaded", "not-found"):
            raise UpdateError("Unexpected systemd timer state: " + value)
        return value == "loaded"
    # Enumerating tasks avoids interpreting localized 'not found' messages as
    # permission errors (or vice versa), and detects disabled name collisions.
    result = execute(["schtasks.exe", "/Query", "/FO", "CSV", "/NH"])
    return any(row and row[0].lstrip("\\").casefold() == name.casefold()
               for row in csv.reader(result.stdout.splitlines()))


def registered(config):
    if not job_exists(config):
        return False
    system, name = config["system"], config["job_name"]
    if system == "Darwin":
        return True
    if system == "Linux":
        active = True
        for action, accepted in (("is-enabled", {"enabled", "disabled", "static", "masked"}),
                                 ("is-active", {"active", "inactive", "failed"})):
            result = execute(["systemctl", "--user", action, name + ".timer"], check=False)
            value = result.stdout.strip()
            if value not in accepted or result.stderr.strip():
                raise UpdateError("Could not inspect systemd timer: " + (result.stderr or result.stdout).strip()[-1500:])
            active = active and value in ("enabled", "active")
        return active
    result = execute(["schtasks.exe", "/Query", "/TN", name, "/XML"])
    try:
        return ET.fromstring(result.stdout).findtext("{*}Settings/{*}Enabled") != "false"
    except ET.ParseError as exc:
        raise UpdateError("Could not read the scheduled task state.") from exc


def register(config):
    system, name = config["system"], config["job_name"]
    if system == "Darwin":
        target = f"gui/{os.getuid()}/{name}"
        if registered(config):
            execute(["launchctl", "bootout", target])
        execute(["launchctl", "enable", target])
        execute(["launchctl", "bootstrap", f"gui/{os.getuid()}",
                 str(Path(config["scheduler_dir"]) / (name + ".plist"))])
    elif system == "Linux":
        execute(["systemctl", "--user", "daemon-reload"])
        execute(["systemctl", "--user", "enable", "--now", name + ".timer"])
    else:
        execute(["schtasks.exe", "/Create", "/TN", name, "/XML",
                 str(Path(config["state_dir"]) / "task.xml"), "/F"])
    if not registered(config):
        raise UpdateError("The scheduler did not confirm activation. Automatic updates remain disabled.")


def unregister(config):
    system, name = config["system"], config["job_name"]
    if system == "Darwin":
        if registered(config):
            execute(["launchctl", "bootout", f"gui/{os.getuid()}/{name}"])
    elif system == "Linux":
        execute(["systemctl", "--user", "disable", "--now", name + ".timer"])
    else:
        if job_exists(config):
            execute(["schtasks.exe", "/Delete", "/TN", name, "/F"])
    if registered(config):
        raise UpdateError("The scheduler still reports an active job. Updater configuration is disabled; retry removal.")


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_owned_files(config, require=False):
    for path, digest in config.get("files", {}).items():
        target = Path(path)
        if require and not target.is_file():
            raise UpdateError(f"Required scheduler file is missing: {target}. Re-run setup to repair it.")
        if target.is_symlink() or (target.exists() and file_hash(target) != digest):
            raise UpdateError(f"{target} was modified outside setup; left unchanged.")


def enable(root, executable=None):
    with lock(root):
        old = load_config(root)
        if old:
            check_owned_files(old)
        executable = executable or shutil.which("codex")
        if not executable:
            raise UpdateError("Codex CLI is required. Install it, then retry setup.")
        system = platform.system()
        home = absolute(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
        name = "org.danepps.legal-research-codex." + hashlib.sha256(str(root).encode()).hexdigest()[:12]
        scheduler_dir = (Path.home() / "Library/LaunchAgents" if system == "Darwin" else
                         absolute(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "systemd/user")
        config = {"owner": OWNER, "state_dir": str(root), "enabled": False,
                  "system": system, "job_name": name, "scheduler_dir": str(scheduler_dir),
                  "codex_home": str(home), "codex": str(absolute(executable)),
                  "python": str(absolute(sys.executable)), "path": os.environ.get("PATH", os.defpath)}
        if system == "Windows":
            config["windows_user"] = execute(["whoami"]).stdout.strip()
        plugin = installed_plugin(config)
        if not plugin or plugin.get("enabled") is not True:
            raise UpdateError("Install and enable the native legal-research Codex plugin first. "
                              "Manual skill copies are not updated by this helper.")
        verify_source(plugin)
        files = scheduler_files(config)
        if not old and job_exists(config):
            raise UpdateError("A scheduler job with this name already exists; left unchanged.")
        for path in files:
            if path.is_symlink() or (path.exists() and str(path) not in (old or {}).get("files", {})):
                raise UpdateError(f"Existing scheduler file left unchanged: {path}")
        runner = root / "auto_update.py"
        if runner.exists() and not old:
            raise UpdateError(f"Existing helper left unchanged: {runner}")
        atomic_write(runner, Path(__file__).read_bytes())
        for path, data in files.items():
            atomic_write(path, data)
        config["files"] = {str(path): file_hash(path) for path in files}
        write_json(root / "config.json", config)
        try:
            register(config)
        except UpdateError:
            # Keep the disabled config and helper so even a partially registered
            # job cannot update anything, and 'disable' can retry cleanup.
            raise
        config["enabled"] = True
        write_json(root / "config.json", config)
    return {"enabled": True, "schedule_registered": True, "state_dir": str(root),
            "message": "Automatic updates enabled. Checks run daily while logged in; start a new Codex session to use updates."}


def disable(root):
    if not root.exists():
        return {"enabled": False, "schedule_registered": False}
    with lock(root):
        config = load_config(root)
        if not config:
            return {"enabled": False, "schedule_registered": False}
        config["enabled"] = False
        write_json(root / "config.json", config)
        check_owned_files(config)
        unregister(config)
        for path in config.get("files", {}):
            Path(path).unlink(missing_ok=True)
        if config["system"] == "Linux":
            execute(["systemctl", "--user", "daemon-reload"])
    return {"enabled": False, "schedule_registered": False,
            "message": "Automatic updates disabled. Plugin and research files are unchanged."}


def status(root):
    config = load_config(root)
    result = {"enabled": bool(config and config.get("enabled")), "state_dir": str(root),
              "schedule_registered": False, "last_run": read_json(root / "last-run.json")}
    if config:
        result["codex_home"] = config["codex_home"]
        try:
            result["schedule_registered"] = registered(config)
            check_owned_files(config, require=config.get("enabled", False))
            if config.get("enabled"):
                for path in (root / "auto_update.py", Path(config["python"]), Path(config["codex"])):
                    if not path.is_file():
                        raise UpdateError(f"Required updater executable is missing: {path}. Re-run setup to repair it.")
        except UpdateError as exc:
            result["schedule_registered"] = None
            result["scheduler_error"] = str(exc)
    return result


def run_update(root, force=False):
    config = load_config(root)
    if not config or not config.get("enabled"):
        return {"status": "disabled"}
    with lock(root):
        config = load_config(root)
        if not config or not config.get("enabled"):
            return {"status": "disabled"}
        last = read_json(root / "last-run.json", {})
        now = time.time()
        if not force and 0 <= now - last.get("attempted_at", 0) < DAY:
            return {"status": "not_due", "last_run": last}
        record = {"attempted_at": now, "time": datetime.now().astimezone().isoformat(timespec="seconds"),
                  "status": "running"}
        write_json(root / "last-run.json", record)
        try:
            before = installed_plugin(config)
            if not before or before.get("enabled") is not True:
                record.update(status="skipped", reason="plugin_missing_or_disabled")
            else:
                verify_source(before)
                codex(config, ["plugin", "marketplace", "upgrade", MARKETPLACE])
                # Refresh can install files itself. Recheck before 'add' so a
                # removed/disabled plugin is not deliberately re-enabled.
                current = installed_plugin(config)
                if not current or current.get("enabled") is not True:
                    record.update(status="skipped", reason="plugin_missing_or_disabled_after_refresh")
                else:
                    verify_source(current)
                    codex(config, ["plugin", "add", PLUGIN])
                    after = installed_plugin(config)
                    if not after or not after.get("version") or after.get("enabled") is not True:
                        raise UpdateError("Update command completed, but installed-version readback failed.")
                    verify_source(after)
                    record.update(status="updated" if before.get("version") != after["version"] else "up_to_date",
                                  previous_version=before.get("version"), version=after["version"])
        except UpdateError as exc:
            record.update(status="failed", error=str(exc))
            write_json(root / "last-run.json", record)
            raise
        write_json(root / "last-run.json", record)
        return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=absolute, help="Updater data directory (normally under CODEX_HOME)")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("enable", help="Opt in to daily background plugin updates").add_argument("--codex", help="Absolute Codex executable path")
    commands.add_parser("disable", help="Disable updates and remove the scheduled job")
    commands.add_parser("status", help="Read the schedule and last update result")
    commands.add_parser("run", help="Run a due update if enabled").add_argument("--force", action="store_true", help="Check now, ignoring the daily interval")
    args = parser.parse_args()
    root = args.state_dir or absolute(os.environ.get("CODEX_HOME", Path.home() / ".codex")) / "legal-research-updater"
    try:
        if args.command == "enable":
            result = enable(root, args.codex)
        elif args.command == "disable":
            result = disable(root)
        elif args.command == "status":
            result = status(root)
        else:
            result = run_update(root, args.force)
        print(json.dumps(result, indent=2))
        return 0
    except (UpdateError, OSError) as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
