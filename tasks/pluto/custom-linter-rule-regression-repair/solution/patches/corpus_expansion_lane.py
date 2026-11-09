from __future__ import annotations

from pathlib import Path


def expand_corpus_paths(corpus_dir: Path, manifest_files: list[str]) -> list[Path]:
    paths: list[Path] = []
    for name in manifest_files:
        path = corpus_dir / name
        if path.exists():
            paths.append(path)
    return paths
