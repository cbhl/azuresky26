#!/usr/bin/env python3
"""Resize a cover image to pixel-art PNG dimensions for the bookshelf.

Input dimensions are in millimeters by default. Output dp = round(input * scale).

Workflow:
  1. Run with different --scale values until the auto pass looks close.
  2. Patch the PNG in a pixel editor (GIMP, Aseprite, etc.).
  3. Copy the printed width/height into book front matter [extra].

Requires: pip install Pillow
"""

from __future__ import annotations

import argparse
import sys

try:
    from PIL import Image
except ImportError:
    print("error: Pillow required (pip install Pillow)", file=sys.stderr)
    sys.exit(1)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Convert a cover image to pixel-art PNG.")
    parser.add_argument("--input", required=True, help="Source cover image path")
    parser.add_argument("--output", required=True, help="Output PNG path")
    parser.add_argument("--width", type=float, required=True, help="Input width (mm by default)")
    parser.add_argument("--height", type=float, required=True, help="Input height (mm by default)")
    parser.add_argument(
        "--scale",
        type=float,
        default=0.5,
        help="Output dp per input mm (default: 0.5)",
    )
    parser.add_argument("--colors", type=int, default=32, help="Palette size after quantize")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    out_w = max(1, round(args.width * args.scale))
    out_h = max(1, round(args.height * args.scale))

    img = Image.open(args.input).convert("RGB")
    img = img.resize((out_w, out_h), Image.Resampling.LANCZOS)
    img = img.quantize(colors=args.colors, method=Image.Quantize.MEDIANCUT)

    img.save(args.output, optimize=True)
    print(f"wrote {out_w}×{out_h} dp → {args.output}")
    print(f"[extra]\nwidth = {out_w}\nheight = {out_h}")


if __name__ == "__main__":
    main()
