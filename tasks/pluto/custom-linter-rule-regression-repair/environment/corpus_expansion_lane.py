from __future__ import annotations

from pathlib import Path


def expand_corpus_paths(corpus_dir: Path, manifest_files: list[str]) -> list[Path]:
    if not manifest_files:
        return []
    first = manifest_files[0]
    path = corpus_dir / first
    return [path] if path.exists() else []
