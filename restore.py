#!/usr/bin/env python3
"""Restore base64-protected Gitea HTML/template assets after checkout."""

from __future__ import annotations

import argparse
import base64
import binascii
import fnmatch
import hashlib
import json
import os
import tempfile
from pathlib import Path

MANIFEST_VERSION = 1


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def repository_root() -> Path:
    return Path(__file__).resolve().parent


def safe_target(root: Path, relative_path: str) -> Path:
    if not relative_path or Path(relative_path).is_absolute():
        raise ValueError(f"invalid manifest path: {relative_path!r}")
    target = (root / relative_path).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"manifest path escapes repository root: {relative_path}") from exc
    return target


def load_manifest(path: Path) -> dict[str, object]:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SystemExit(f"manifest not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid manifest JSON: {path}: {exc}") from exc

    if manifest.get("version") != MANIFEST_VERSION:
        raise SystemExit(
            f"unsupported manifest version: {manifest.get('version')!r}; expected {MANIFEST_VERSION}"
        )
    if not isinstance(manifest.get("files"), list):
        raise SystemExit("manifest field 'files' must be a list")
    return manifest


def decode_payload(payload_path: Path) -> bytes:
    try:
        encoded = b"".join(payload_path.read_bytes().split())
    except FileNotFoundError as exc:
        raise RuntimeError(f"payload missing: {payload_path}") from exc
    try:
        return base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise RuntimeError(f"invalid base64 payload: {payload_path}: {exc}") from exc


def validate_entry(entry: object) -> dict[str, object]:
    if not isinstance(entry, dict):
        raise RuntimeError("manifest file entry must be an object")
    required = {"path": str, "payload": str, "sha256": str, "size": int, "mode": int}
    for key, expected_type in required.items():
        if not isinstance(entry.get(key), expected_type):
            raise RuntimeError(f"manifest entry field {key!r} has the wrong type")
    return entry


def matches_filters(path: str, filters: list[str]) -> bool:
    return not filters or any(fnmatch.fnmatch(path, pattern) for pattern in filters)


def atomic_write(path: Path, data: bytes, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def current_digest(path: Path) -> str | None:
    try:
        return sha256_bytes(path.read_bytes())
    except FileNotFoundError:
        return None


def run(root: Path, manifest_path: Path, check: bool, dry_run: bool, filters: list[str]) -> int:
    root = root.resolve()
    manifest_path = manifest_path.resolve()
    manifest = load_manifest(manifest_path)
    store = manifest_path.parent

    failures = 0
    selected = 0
    restored = 0

    for raw_entry in manifest["files"]:
        entry = validate_entry(raw_entry)
        relative = str(entry["path"])
        if not matches_filters(relative, filters):
            continue
        selected += 1

        target = safe_target(root, relative)
        payload_path = safe_target(store, str(entry["payload"]))
        data = decode_payload(payload_path)
        expected_size = int(entry["size"])
        expected_digest = str(entry["sha256"])

        if len(data) != expected_size:
            print(f"ERROR {relative}: payload size {len(data)} != {expected_size}")
            failures += 1
            continue
        payload_digest = sha256_bytes(data)
        if payload_digest != expected_digest:
            print(f"ERROR {relative}: payload SHA-256 {payload_digest} != {expected_digest}")
            failures += 1
            continue

        existing_digest = current_digest(target)
        if existing_digest == expected_digest:
            print(f"OK    {relative}")
            continue

        if check:
            state = "MISSING" if existing_digest is None else "DIFF"
            print(f"{state:<7}{relative}")
            failures += 1
            continue

        if dry_run:
            action = "CREATE" if existing_digest is None else "RESTORE"
            print(f"{action:<7}{relative}")
            continue

        atomic_write(target, data, int(entry["mode"]))
        if current_digest(target) != expected_digest:
            print(f"ERROR {relative}: verification after restore failed")
            failures += 1
            continue
        print(f"RESTORED {relative}")
        restored += 1

    if selected == 0:
        print("No manifest entries matched.")
        return 1 if filters else 0

    if failures:
        print(f"Completed with {failures} failure(s).")
        return 1

    if not check and not dry_run:
        print(f"Restore complete: {restored} file(s) rewritten, {selected - restored} already valid.")
    return 0


def parse_args() -> argparse.Namespace:
    root = repository_root()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=root, help="repository root")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=root / "tools" / "html_asset_restore" / "manifest.json",
    )
    parser.add_argument("--check", action="store_true", help="verify without writing")
    parser.add_argument("--dry-run", action="store_true", help="show what would be restored")
    parser.add_argument(
        "--only",
        action="append",
        default=[],
        metavar="GLOB",
        help="restore only matching manifest paths; may be repeated",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.check and args.dry_run:
        raise SystemExit("--check and --dry-run cannot be used together")
    return run(args.root, args.manifest, args.check, args.dry_run, args.only)


if __name__ == "__main__":
    raise SystemExit(main())
