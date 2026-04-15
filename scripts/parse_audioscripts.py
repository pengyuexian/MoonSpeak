#!/usr/bin/env python3

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from moonspeak.audioscripts_parser import parse_audioscripts_pdf, write_unit_markdown_files


def main() -> int:
    parser = argparse.ArgumentParser(description="Parse Power Up audioscripts PDF into unit markdown files.")
    parser.add_argument("pdf_path", help="Path to the source audioscripts PDF.")
    parser.add_argument("output_dir", help="Directory for generated unit markdown files.")
    args = parser.parse_args()

    units = parse_audioscripts_pdf(args.pdf_path)
    paths = write_unit_markdown_files(units, args.output_dir)
    print(f"Wrote {len(paths)} files to {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
