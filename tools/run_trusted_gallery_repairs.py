#!/usr/bin/env python3
"""Run the trusted gallery repair harvester with the contact-sheet fix."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

import harvest_trusted_gallery_repairs as harvest


def make_contact_sheet(game: str, rows: list[dict[str, Any]], output: Path) -> None:
    cols = 5
    cell_w, image_h, label_h = 320, 210, 42
    row_count = max(1, math.ceil(len(rows) / cols))
    header_h = 62
    canvas = Image.new("RGB", (cols * cell_w, header_h + row_count * (image_h + label_h)), "#101010")
    draw = ImageDraw.Draw(canvas)
    draw.text((18, 15), f"{game} — {len(rows)} trusted gallery frames", fill="white", font=harvest.load_font(24))
    for idx, row in enumerate(rows):
        r, c = divmod(idx, cols)
        x, y = c * cell_w, header_h + r * (image_h + label_h)
        image = Image.open(row["absolute_path"]).convert("RGB")
        image.thumbnail((cell_w, image_h), Image.Resampling.LANCZOS)
        frame = Image.new("RGB", (cell_w, image_h), "black")
        frame.paste(image, ((cell_w - image.width) // 2, (image_h - image.height) // 2))
        canvas.paste(frame, (x, y))
        draw.rectangle((x, y + image_h, x + cell_w, y + image_h + label_h), fill="#1d1d1d")
        draw.text(
            (x + 8, y + image_h + 10),
            f"{idx + 1:02d} · {row['source_domain']} · {row['version']}",
            fill="white",
            font=harvest.load_font(14),
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output, quality=92)


harvest.make_contact_sheet = make_contact_sheet

if __name__ == "__main__":
    raise SystemExit(harvest.main())
