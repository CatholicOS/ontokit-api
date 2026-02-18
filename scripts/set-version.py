#!/usr/bin/env python3
"""Set the next development version for Axigraph.

Usage:
    python scripts/set-version.py 0.2.0

This will:
  1. Update axigraph/version.py to "0.2.0-dev"
  2. Create a git commit: "chore: setting version to 0.2.0-dev"
"""

import re
import subprocess
import sys
from pathlib import Path

VERSION_FILE = Path(__file__).resolve().parent.parent / "axigraph" / "version.py"


def main() -> int:
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <version>")
        print("Example: python scripts/set-version.py 0.2.0")
        return 1

    version = sys.argv[1]

    # Validate version format
    if not re.match(r"^\d+\.\d+\.\d+$", version):
        print(f"Error: Invalid version format '{version}'. Expected X.Y.Z")
        return 1

    dev_version = f"{version}-dev"

    # Update version.py
    content = VERSION_FILE.read_text()
    content = re.sub(r'VERSION = "[^"]+"', f'VERSION = "{dev_version}"', content)
    VERSION_FILE.write_text(content)
    print(f"Updated {VERSION_FILE} to {dev_version}")

    # Git commit
    subprocess.run(["git", "add", str(VERSION_FILE)], check=True)
    subprocess.run(
        ["git", "commit", "-m", f"chore: setting version to {dev_version}"],
        check=True,
    )
    print(f"Created commit: chore: setting version to {dev_version}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
