"""Isolated parser process; the API imposes a wall-clock timeout."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--validate", action="store_true")
    parser.add_argument("--engine", default="offline", choices=["offline", "docling-native"])
    args = parser.parse_args()
    if args.validate:
        from .security import validate_upload
        result = {"media_type": validate_upload(args.source.name, args.source.read_bytes())}
    else:
        from .extraction import extract_document
        result = extract_document(args.source, args.output.parent / "pages", engine=args.engine)
    args.output.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
