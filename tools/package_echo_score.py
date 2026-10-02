#!/usr/bin/env python3
"""Build a reproducible, cache-free echo-score.zip using the standard library."""

import argparse
from pathlib import Path
import zipfile


ROOT = Path(__file__).resolve().parents[1]
CACHE_DIRECTORIES = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)


def build_archive(source, output):
    """Write sorted source bytes with fixed metadata and the echo-score/ prefix.

    ZIP_STORED avoids platform/zlib-version differences in compressed output;
    this small Python-only distribution does not need a compression dependency.
    """
    source = Path(source)
    output = Path(output)
    if not source.is_dir():
        raise ValueError(f"Source directory does not exist: {source}")
    files = []
    for path in source.rglob("*"):
        relative = path.relative_to(source)
        if (CACHE_DIRECTORIES.intersection(relative.parts)
                or path.suffix.lower() in {".pyc", ".pyo"}
                or path.name == ".DS_Store"):
            continue
        if path.is_file():
            files.append(("echo-score/" + relative.as_posix(), path.read_bytes()))

    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, data in sorted(files):
            info = zipfile.ZipInfo(name, date_time=ZIP_EPOCH)
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_STORED
            archive.writestr(info, data)
    return len(files)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "echo-score")
    parser.add_argument("--output", type=Path, default=ROOT / "echo-score.zip")
    args = parser.parse_args()
    count = build_archive(args.source, args.output)
    print(f"Packaged {count} files into {args.output}")


if __name__ == "__main__":
    main()
