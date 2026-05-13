"""Render a launchd plist for daily signal-learning input collection."""

from __future__ import annotations

import argparse
import plistlib
import sys
from pathlib import Path
from typing import Any


DEFAULT_LABEL = "com.quantum-electronics.signal-learning-daily"


def build_launchd_plist(
    *,
    repo_dir: Path,
    python_executable: str,
    label: str = DEFAULT_LABEL,
    hour: int = 16,
    minute: int = 10,
    stock_limit: int = 3,
    force_kis_token: bool = False,
) -> dict[str, Any]:
    command = [
        python_executable,
        str(repo_dir / "scripts" / "collect_daily_signal_learning_inputs.py"),
        "--kis-auth",
        "--stock-limit",
        str(stock_limit),
        "--run-workflow-if-ready",
    ]
    if force_kis_token:
        command.insert(3, "--force-kis-token")

    runtime_dir = repo_dir / "runtime"
    return {
        "Label": label,
        "ProgramArguments": command,
        "WorkingDirectory": str(repo_dir),
        "StartCalendarInterval": {
            "Hour": hour,
            "Minute": minute,
        },
        "StandardOutPath": str(runtime_dir / "signal_learning_daily.out.log"),
        "StandardErrorPath": str(runtime_dir / "signal_learning_daily.err.log"),
        "RunAtLoad": False,
    }


def render_plist(plist: dict[str, Any]) -> bytes:
    return plistlib.dumps(plist, sort_keys=False)


def main() -> int:
    parser = argparse.ArgumentParser(description="Render a launchd plist for daily signal learning collection")
    parser.add_argument("--repo-dir", default=Path.cwd(), type=Path)
    parser.add_argument("--python", default=sys.executable, help="Python executable used by launchd")
    parser.add_argument("--label", default=DEFAULT_LABEL)
    parser.add_argument("--hour", default=16, type=int)
    parser.add_argument("--minute", default=10, type=int)
    parser.add_argument("--stock-limit", default=3, type=int)
    parser.add_argument("--force-kis-token", action="store_true")
    parser.add_argument("--output", type=Path, help="Optional plist output path; stdout is used when omitted")
    args = parser.parse_args()

    plist = build_launchd_plist(
        repo_dir=args.repo_dir.resolve(),
        python_executable=args.python,
        label=args.label,
        hour=args.hour,
        minute=args.minute,
        stock_limit=args.stock_limit,
        force_kis_token=args.force_kis_token,
    )
    rendered = render_plist(plist)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(rendered)
    else:
        sys.stdout.buffer.write(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
