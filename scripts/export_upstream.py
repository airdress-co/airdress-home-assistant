#!/usr/bin/env python3
"""Refresh upstream/ from a Home Assistant core checkout.

The integration is written in a branch of home-assistant/core. That branch is
not public until it is submitted upstream, so this repository cannot fetch it:
instead it carries a committed, verbatim snapshot of the files it needs, in
upstream/, and generate.py builds everything else from that snapshot. This
script is how a maintainer takes the snapshot.

    scripts/export_upstream.py --core ../ha-core            # take a snapshot
    scripts/export_upstream.py --core ../ha-core --check    # compare only

It refuses a core tree with uncommitted changes to the integration, so every
snapshot names a real commit in upstream/SOURCE. translations/en.json is not
committed in core (core generates it from strings.json), so it is generated
here with core's own script before it is copied.

After a snapshot, run scripts/generate.py and commit upstream/ together with
what it generated.
"""

from __future__ import annotations

import argparse
import filecmp
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UPSTREAM = ROOT / "upstream"

# What the mirror takes from core, as paths relative to the core checkout.
TREES = (
    "homeassistant/components/airdress",
    "tests/components/airdress",
)
FILES = (
    # The logbook test helper the integration's logbook test imports. The
    # custom-component test harness does not ship core's test helpers.
    "tests/components/logbook/common.py",
)
IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc")


def git(core: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(core), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def generate_translations(core: Path) -> None:
    python = core / ".venv" / "bin" / "python"
    if not python.exists():
        sys.exit(f"no core virtualenv at {python}: set one up with core's script/setup")
    subprocess.run(
        [str(python), "-m", "script.translations", "develop", "--integration", "airdress"],
        cwd=core,
        check=True,
    )


def copy_into(core: Path, dest: Path) -> None:
    for tree in TREES:
        shutil.copytree(core / tree, dest / tree, ignore=IGNORE)
    for file in FILES:
        (dest / file).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(core / file, dest / file)


def differences(left: Path, right: Path) -> list[str]:
    """Relative paths that differ between two trees, in either direction."""
    found: list[str] = []

    def walk(cmp: filecmp.dircmp[str], prefix: str) -> None:
        for name in cmp.left_only + cmp.right_only + cmp.funny_files:
            found.append(prefix + name)
        _, mismatch, errors = filecmp.cmpfiles(
            cmp.left, cmp.right, cmp.common_files, shallow=False
        )
        found.extend(prefix + name for name in mismatch + errors)
        for name, sub in cmp.subdirs.items():
            walk(sub, f"{prefix}{name}/")

    walk(filecmp.dircmp(left, right, ignore=["__pycache__", "SOURCE"]), "")
    return sorted(found)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--core", type=Path, required=True, help="a home-assistant/core checkout")
    parser.add_argument("--check", action="store_true", help="compare, do not write")
    args = parser.parse_args()
    core: Path = args.core.resolve()

    dirty = git(core, "status", "--porcelain", "--", *TREES, *FILES)
    if dirty and not args.check:
        sys.exit(f"uncommitted changes in the core tree:\n{dirty}")
    generate_translations(core)

    staging = ROOT / ".export-staging"
    shutil.rmtree(staging, ignore_errors=True)
    copy_into(core, staging)

    if args.check:
        diff = differences(staging, UPSTREAM)
        shutil.rmtree(staging)
        if diff:
            sys.exit("upstream/ differs from the core checkout:\n  " + "\n  ".join(diff))
        print("upstream/ matches the core checkout")
        return

    commit = git(core, "rev-parse", "HEAD")
    (staging / "SOURCE").write_text(
        "The Home Assistant core files this mirror is generated from.\n"
        f"branch: {git(core, 'rev-parse', '--abbrev-ref', 'HEAD')}\n"
        f"commit: {commit}\n"
        f"committed: {git(core, 'show', '-s', '--format=%cI', commit)}\n"
        f"subject: {git(core, 'show', '-s', '--format=%s', commit)}\n"
    )
    shutil.rmtree(UPSTREAM, ignore_errors=True)
    staging.rename(UPSTREAM)
    print(f"upstream/ now holds {commit[:10]}; run scripts/generate.py next")


if __name__ == "__main__":
    main()
