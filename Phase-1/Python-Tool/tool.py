#!/usr/bin/env python3
"""Simple SHA-256 File Integrity Checker (Python standard library only)."""

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

CHUNK_SIZE = 1024 * 1024  # Read large files in 1 MiB chunks.


def sha256_file(path: Path) -> str:
    """Compute SHA-256 without loading the entire file into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def default_baseline(file_path: Path) -> Path:
    return file_path.with_name(file_path.name + ".sha256.json")


def get_valid_file(path_string: str) -> Path:
    path = Path(path_string).expanduser()
    if not path.is_file():
        raise ValueError(f"File does not exist or is not a regular file: {path}")
    return path


def hash_command(file_path: Path) -> int:
    print(f"File:   {file_path}")
    print(f"SHA256: {sha256_file(file_path)}")
    return 0


def baseline_command(file_path: Path, baseline_path: Path, force: bool) -> int:
    digest = sha256_file(file_path)
    record = {
        "tool": "Simple File Integrity Checker",
        "algorithm": "sha256",
        "file_name": file_path.name,
        "file_size_bytes": file_path.stat().st_size,
        "sha256": digest,
        "created_utc": datetime.now(timezone.utc).isoformat(),
    }
    # Exclusive creation prevents accidental replacement of an existing baseline.
    mode = "w" if force else "x"
    try:
        with baseline_path.open(mode, encoding="utf-8") as handle:
            json.dump(record, handle, indent=2)
            handle.write("\n")
    except FileExistsError:
        print(
            f"ERROR: Baseline already exists: {baseline_path}. "
            "Use --force only if you intentionally want to replace it.",
            file=sys.stderr,
        )
        return 2
    if os.name == "posix":
        baseline_path.chmod(0o600)
    print("[OK] SHA-256 baseline created.")
    print(f"File:     {file_path}")
    print(f"Baseline: {baseline_path}")
    print(f"SHA256:   {digest}")
    return 0


def verify_command(file_path: Path, baseline_path: Path) -> int:
    if not baseline_path.is_file():
        print(f"ERROR: Baseline not found: {baseline_path}", file=sys.stderr)
        return 2
    try:
        with baseline_path.open("r", encoding="utf-8") as handle:
            record = json.load(handle)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        print(f"ERROR: Invalid baseline JSON: {exc}", file=sys.stderr)
        return 2

    if not isinstance(record, dict) or record.get("algorithm") != "sha256":
        print("ERROR: Baseline has an unsupported or missing algorithm.", file=sys.stderr)
        return 2
    expected = record.get("sha256")
    if not isinstance(expected, str) or len(expected) != 64 or any(
        c not in "0123456789abcdef" for c in expected
    ):
        print("ERROR: Baseline contains an invalid SHA-256 digest.", file=sys.stderr)
        return 2
    if record.get("file_name") != file_path.name:
        print("ERROR: Baseline was created for a different file name.", file=sys.stderr)
        return 2

    actual = sha256_file(file_path)
    print(f"File:     {file_path}")
    print(f"Baseline: {baseline_path}")
    print(f"Expected: {expected}")
    print(f"Actual:   {actual}")
    if actual == expected:
        print("[PASS] File content matches the saved baseline.")
        return 0
    print("[ALERT] File content has CHANGED since the baseline was created!")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Hash one file and detect changes using a saved SHA-256 baseline."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    hash_parser = sub.add_parser("hash", help="Show the SHA-256 of a file")
    hash_parser.add_argument("file", help="File to hash")

    baseline_parser = sub.add_parser("baseline", help="Save the expected SHA-256")
    baseline_parser.add_argument("file", help="File to protect")
    baseline_parser.add_argument("--db", help="Optional baseline JSON path")
    baseline_parser.add_argument(
        "--force", action="store_true", help="Intentionally overwrite an existing baseline"
    )

    verify_parser = sub.add_parser("verify", help="Compare a file to its baseline")
    verify_parser.add_argument("file", help="File to check")
    verify_parser.add_argument("--db", help="Optional baseline JSON path")

    args = parser.parse_args()
    try:
        file_path = get_valid_file(args.file)
        if args.command == "hash":
            return hash_command(file_path)
        baseline_path = Path(args.db).expanduser() if args.db else default_baseline(file_path)
        if baseline_path.resolve() == file_path.resolve():
            raise ValueError("The baseline path must not be the same as the file being checked.")
        if baseline_path.is_symlink():
            raise ValueError("Refusing to write or read a baseline through a symbolic link.")
        if args.command == "baseline":
            return baseline_command(file_path, baseline_path, args.force)
        return verify_command(file_path, baseline_path)
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
