#!/usr/bin/env python3
"""Create base64 payloads for Gitea templates that may be rewritten in transit."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import stat
import subprocess
from pathlib import Path

DEFAULT_PATTERNS = ("templates/**/*.tmpl",)
MANIFEST_VERSION = 1


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def current_commit(root: Path) -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def ensure_inside_root(root: Path, candidate: Path) -> Path:
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"path escapes repository root: {candidate}") from exc
    return resolved


def collect_files(root: Path, patterns: list[str]) -> list[Path]:
    files: set[Path] = set()
    for pattern in patterns:
        for candidate in root.glob(pattern):
            if not candidate.is_file() or candidate.is_symlink():
                continue
            files.add(ensure_inside_root(root, candidate))
    return sorted(files, key=lambda path: path.relative_to(root).as_posix())


def encode_wrapped(data: bytes) -> str:
    encoded = base64.b64encode(data).decode("ascii")
    return "\n".join(encoded[index : index + 76] for index in range(0, len(encoded), 76)) + "\n"


def write_if_changed(path: Path, content: str) -> None:
    encoded = content.encode("utf-8")
    if path.exists() and path.read_bytes() == encoded:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.write_bytes(encoded)
    os.replace(temporary, path)


def pack(root: Path, store: Path, patterns: list[str]) -> int:
    root = root.resolve()
    store = ensure_inside_root(root, store)
    payload_dir = store / "payload"
    payload_dir.mkdir(parents=True, exist_ok=True)

    entries: list[dict[str, object]] = []
    expected_payloads: set[str] = set()

    for source in collect_files(root, patterns):
        relative = source.relative_to(root).as_posix()
        data = source.read_bytes()
        digest = sha256_bytes(data)
        payload_name = f"{hashlib.sha256(relative.encode('utf-8')).hexdigest()}.b64"
        expected_payloads.add(payload_name)
        write_if_changed(payload_dir / payload_name, encode_wrapped(data))
        entries.append(
            {
                "path": relative,
                "payload": f"payload/{payload_name}",
                "sha256": digest,
                "size": len(data),
                "mode": stat.S_IMODE(source.stat().st_mode),
            }
        )

    for stale in payload_dir.glob("*.b64"):
        if stale.name not in expected_payloads:
            stale.unlink()

    manifest = {
        "version": MANIFEST_VERSION,
        "source_commit": current_commit(root),
        "patterns": patterns,
        "files": entries,
    }
    write_if_changed(store / "manifest.json", json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(f"Packed {len(entries)} file(s) into {store.relative_to(root)}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=repository_root())
    parser.add_argument(
        "--store",
        type=Path,
        default=repository_root() / "tools" / "html_asset_restore",
    )
    parser.add_argument(
        "--include",
        action="append",
        dest="patterns",
        help="glob relative to repository root; may be repeated",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    patterns = args.patterns or list(DEFAULT_PATTERNS)
    return pack(args.root, args.store, patterns)


if __name__ == "__main__":
    raise SystemExit(main())
