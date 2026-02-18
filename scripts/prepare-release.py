#!/usr/bin/env python3
"""Prepare a release by stripping the -dev suffix from the version.

Usage:
    python scripts/prepare-release.py

This will:
  1. Read the current version from axigraph/version.py (e.g. "0.2.0-dev")
  2. Strip the -dev suffix → "0.2.0"
  3. Update axigraph/version.py
  4. Create a git commit: "chore: releasing 0.2.0"
"""

import re
import subprocess
import sys
from pathlib import Path

VERSION_FILE = Path(__file__).resolve().parent.parent / "axigraph" / "version.py"


def main() -> int:
    content = VERSION_FILE.read_text()

    match = re.search(r'VERSION = "([^"]+)"', content)
    if not match:
        print("Error: Could not find VERSION in version.py")
        return 1

    current = match.group(1)
    if "-dev" not in current and "-rc" not in current:
        print(f"Error: Current version '{current}' has no -dev or -rc suffix to strip")
        return 1

    release = current.replace("-dev", "").replace("-rc", "")
    content = content.replace(f'VERSION = "{current}"', f'VERSION = "{release}"')
    VERSION_FILE.write_text(content)
    print(f"Updated {VERSION_FILE}: {current} -> {release}")

    # Git commit
    subprocess.run(["git", "add", str(VERSION_FILE)], check=True)
    subprocess.run(
        ["git", "commit", "-m", f"chore: releasing {release}"],
        check=True,
    )
    print(f"Created commit: chore: releasing {release}")
    print(f"\nNext steps:")
    print(f"  git tag -s axigraph-{release}")
    print(f"  git push --tags")

    return 0


if __name__ == "__main__":
    sys.exit(main())
