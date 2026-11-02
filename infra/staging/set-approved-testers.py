#!/usr/bin/env python3
"""Store two explicitly approved sub UUIDs locally. No AWS/network calls."""

import getpass
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
PRIVATE = ROOT / ".staging"
PARAMETERS = PRIVATE / "parameters.json"
SUB = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


def main():
    if not sys.stdin.isatty():
        raise SystemExit("Run interactively in your terminal so subject IDs stay hidden.")
    ignored = subprocess.run(
        ["git", "check-ignore", "--quiet", "--", ".staging/parameters.json"], cwd=ROOT
    )
    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "--", ".staging/parameters.json"],
        cwd=ROOT, capture_output=True,
    )
    if ignored.returncode != 0 or tracked.returncode == 0:
        raise SystemExit("Refusing: the parameter file must be ignored and untracked.")
    if PRIVATE.is_symlink() or PARAMETERS.is_symlink():
        raise SystemExit("Refusing a symlink for private parameters.")
    values = json.loads(PARAMETERS.read_text())
    targets = [p for p in values if p.get("ParameterKey") == "StagingAllowedUserSubs"]
    if len(targets) != 1:
        raise SystemExit("Expected exactly one StagingAllowedUserSubs parameter.")
    first = getpass.getpass("First approved, confirmed synthetic user's sub (hidden): ").strip().lower()
    second = getpass.getpass("Second approved, confirmed synthetic user's sub (hidden): ").strip().lower()
    if not SUB.fullmatch(first) or not SUB.fullmatch(second) or first == second:
        raise SystemExit("Two distinct Cognito sub UUIDs are required; nothing saved.")
    targets[0]["ParameterValue"] = first + "," + second
    PRIVATE.chmod(0o700)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=PRIVATE, delete=False) as temporary:
            temp_path = Path(temporary.name)
            os.chmod(temp_path, 0o600)
            temporary.write(json.dumps(values, indent=2) + "\n")
        os.replace(temp_path, PARAMETERS)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()
    print("Saved two approved subject IDs to ignored .staging/parameters.json (0600).")
    print("No account verification performed. Deployment remains blocked pending its separate gates.")


if __name__ == "__main__":
    try:
        main()
    except (EOFError, KeyboardInterrupt):
        raise SystemExit("Cancelled; nothing saved.") from None
