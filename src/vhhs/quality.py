"""Checks that the committed snapshot still matches its manifest."""

from __future__ import annotations

import hashlib
import json

from vhhs.paths import ROOT, SNAPSHOT


def file_sha256(path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_manifest() -> dict:
    path = SNAPSHOT.parent / "manifest.json"
    if not path.exists():
        raise FileNotFoundError(f"missing manifest at {path}")
    return json.loads(path.read_text())


def verify_manifest() -> dict:
    manifest = load_manifest()
    problems = []
    for item in manifest["files"]:
        path = ROOT / item["path"]
        if not path.exists():
            problems.append(f"missing {item['path']}")
            continue
        digest = file_sha256(path)
        if digest != item["sha256"]:
            problems.append(f"checksum mismatch {item['path']}")
        if path.stat().st_size != item["bytes"]:
            problems.append(f"size mismatch {item['path']}")
    if problems:
        raise RuntimeError("snapshot manifest failed: " + "; ".join(problems))
    return manifest
