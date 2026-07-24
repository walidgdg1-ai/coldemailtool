#!/usr/bin/env python3
"""Package per-game HD hybrid artifacts with strict count validation."""
from __future__ import annotations

import json
import math
import shutil
import sys
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import harvest_game_screenshots as base


def font(size: int):
    for path in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ):
        if Path(path).exists():
            return ImageFont.truetype(path, size=size)
    return ImageFont.load_default()


def locate_game_dir(parts: Path, ordinal: int, slug: str) -> Path | None:
    expected = f"{ordinal:02d}_{slug}"
    matches = sorted(parts.rglob(expected))
    for match in matches:
        if match.is_dir() and (match / "images_hd_extra").is_dir():
            return match
    return None


def make_master_contact(rows: list[dict], output: Path) -> None:
    cols = 4
    tile_w, tile_h, header_h, label_h = 520, 340, 82, 52
    canvas = Image.new(
        "RGB",
        (cols * tile_w, header_h + math.ceil(len(rows) / cols) * (tile_h + label_h)),
        "#0d0d0d",
    )
    draw = ImageDraw.Draw(canvas)
    complete = sum(row["status"] == "complete" for row in rows)
    draw.text(
        (22, 20),
        f"AI PROD · Additional HD Gameplay Bank · {complete}/31 games complete",
        fill="white",
        font=font(30),
    )
    for idx, row in enumerate(rows):
        rr, cc = divmod(idx, cols)
        x, y = cc * tile_w, header_h + rr * (tile_h + label_h)
        sheet_path = row.get("contact_sheet_path")
        frame = Image.new("RGB", (tile_w, tile_h), "#111111")
        if sheet_path and Path(sheet_path).exists():
            image = Image.open(sheet_path).convert("RGB")
            image.thumbnail((tile_w, tile_h), Image.Resampling.LANCZOS)
            frame.paste(image, ((tile_w - image.width) // 2, (tile_h - image.height) // 2))
        else:
            missing_draw = ImageDraw.Draw(frame)
            missing_draw.text((24, 130), "INCOMPLETE / NO CONTACT SHEET", fill="white", font=font(21))
        canvas.paste(frame, (x, y))
        draw.rectangle((x, y + tile_h, x + tile_w, y + tile_h + label_h), fill="#1b1b1b")
        status = "15/15" if row["status"] == "complete" else f"{row.get('selected_count', 0)}/15"
        native = row.get("native_hd_count", 0)
        draw.text(
            (x + 10, y + tile_h + 13),
            f"{row['ordinal']:02d} · {row['game']} · {status} · native {native}",
            fill="white",
            font=font(16),
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output, quality=92)


def main() -> int:
    if len(sys.argv) < 3:
        raise SystemExit("Usage: package_hd_hybrid_results.py PARTS_DIR OUTPUT_DIR")
    parts = Path(sys.argv[1]).resolve()
    output = Path(sys.argv[2]).resolve()
    if output.exists():
        shutil.rmtree(output)
    bank = output / "HD_EXTRA_REFERENCE_BANK"
    bank.mkdir(parents=True, exist_ok=True)

    rows: list[dict] = []
    for ordinal, game in enumerate(base.GAMES, 1):
        slug = base.slugify(game["name"])
        source = locate_game_dir(parts, ordinal, slug)
        row = {
            "ordinal": ordinal,
            "game": game["name"],
            "slug": slug,
            "status": "missing",
            "selected_count": 0,
            "native_hd_count": 0,
            "marked_upscaled_fallback_count": 0,
            "errors": [],
        }
        if source is None:
            row["errors"].append("game artifact directory not found")
            rows.append(row)
            continue
        destination = bank / source.name
        shutil.copytree(source, destination)
        images = sorted((destination / "images_hd_extra").glob("*.jpg"))
        manifests = sorted(destination.glob("manifest_*_hd_extra.json"))
        contacts = sorted(destination.glob("contact_sheet_*_hd_extra.jpg"))
        row["selected_count"] = len(images)
        if len(images) != 15:
            row["errors"].append(f"expected 15 images, found {len(images)}")
        if not manifests:
            row["errors"].append("manifest missing")
        else:
            try:
                manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
                row["manifest_selected_count"] = manifest.get("selected_count")
                row["native_hd_count"] = manifest.get("native_hd_count", 0)
                row["marked_upscaled_fallback_count"] = manifest.get("marked_upscaled_fallback_count", 0)
                row["selected_source_counts"] = manifest.get("selected_source_counts", {})
                if manifest.get("selected_count") != 15:
                    row["errors"].append(
                        f"manifest selected_count is {manifest.get('selected_count')}"
                    )
            except Exception as exc:
                row["errors"].append(f"manifest parse error: {exc}")
        if contacts:
            row["contact_sheet"] = contacts[0].relative_to(output).as_posix()
            row["contact_sheet_path"] = str(contacts[0])
        else:
            row["errors"].append("contact sheet missing")
        if not row["errors"]:
            row["status"] = "complete"
        else:
            row["status"] = "incomplete"
        rows.append(row)

    complete = [row for row in rows if row["status"] == "complete"]
    manifest = {
        "requested_games": 31,
        "target_per_game": 15,
        "requested_total_images": 465,
        "complete_games": len(complete),
        "complete_images": sum(row["selected_count"] for row in complete),
        "native_hd_selected": sum(row["native_hd_count"] for row in complete),
        "marked_upscaled_fallback_selected": sum(
            row["marked_upscaled_fallback_count"] for row in complete
        ),
        "all_complete": len(complete) == 31,
        "games": [
            {k: v for k, v in row.items() if k != "contact_sheet_path"}
            for row in rows
        ],
    }
    (output / "MASTER_HD_EXTRA_MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    make_master_contact(rows, output / "MASTER_HD_EXTRA_CONTACT_SHEET.jpg")

    zip_path = Path("AI_PROD_HD_EXTRA_15_PER_GAME.zip").resolve()
    zip_path.unlink(missing_ok=True)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(output.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(output.parent))
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    print(f"ZIP={zip_path}")
    # Partial packages remain available for diagnosis, but workflow callers can
    # detect incomplete status from this non-zero exit.
    return 0 if manifest["all_complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
