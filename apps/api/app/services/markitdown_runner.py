from __future__ import annotations

import argparse
import io
import json
import sys


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Isolated MarkItDown stream converter")
    parser.add_argument("--file-name", required=True)
    parser.add_argument("--media-type")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        from markitdown import MarkItDown
    except ImportError as exc:
        print(f"MarkItDown import failed: {exc}", file=sys.stderr)
        return 2

    payload = sys.stdin.buffer.read()
    stream = io.BytesIO(payload)
    stream.name = args.file_name

    try:
        converter = MarkItDown(enable_plugins=False)
        result = converter.convert_stream(stream)
    except Exception as exc:
        print(f"MarkItDown conversion failed: {exc}", file=sys.stderr)
        return 3

    markdown = getattr(result, "text_content", None)
    if markdown is None:
        markdown = getattr(result, "markdown", None)
    print(json.dumps({"markdown": markdown or ""}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
