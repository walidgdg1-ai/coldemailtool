#!/usr/bin/env python3
"""Merge per-game harvest artifacts into one reviewed reference-bank ZIP."""

from __future__ import annotations

import json
import math
import re
import shutil
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def load_font(size: int):
    for candidate in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ):
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size=size)
    return ImageFont.load_default()


def make_master_sheet(entries: list[dict], output: Path) -> None:
    usable = [entry for entry in entries if entry.get("contact_sheet")]
    if not usable:
        return
    cols = 3
    cell_w, cell_h = 520, 330
    rows = math.ceil(len(usable) / cols)
    canvas = Image.new("RGB", (cols * cell_w, rows * cell_h), "#0e0e0e")
    draw = ImageDraw.Draw(canvas)
    font = load_font(19)
    for idx, entry in enumerate(usable):
        row, col = divmod(idx, cols)
        x, y = col * cell_w, row * cell_h
        image = Image.open(entry["contact_sheet"]).convert("RGB")
        image.thumbnail((cell_w - 12, cell_h - 44), Image.Resampling.LANCZOS)
        canvas.paste(image, (x + (cell_w - image.width) // 2, y + 4))
        label = f"{entry['ordinal']:02d}. {entry['game']} — {entry['selected_count']}/15"
        draw.text((x + 10, y + cell_h - 32), label, fill="white", font=font)
    canvas.save(output, quality=91)


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit("Usage: package_game_harvests.py PARTS_DIR FINAL_DIR")
    parts_dir = Path(sys.argv[1]).resolve()
    final_parent = Path(sys.argv[2]).resolve()
    root = final_parent / "GAMEPLAY_REFERENCE_BANK"
    if final_parent.exists():
        shutil.rmtree(final_parent)
    root.mkdir(parents=True, exist_ok=True)

    game_dirs: dict[int, Path] = {}
    logs_dir = root / "RUN_LOGS"
    logs_dir.mkdir(exist_ok=True)

    for path in sorted(parts_dir.rglob("*")):
        if path.is_dir():
            match = re.match(r"^(\d{2})_", path.name)
            if match and any(path.glob("manifest_*.json")):
                ordinal = int(match.group(1))
                game_dirs.setdefault(ordinal, path)
        elif path.name.startswith("harvest_") and path.suffix == ".log":
            shutil.copy2(path, logs_dir / path.name)

    entries: list[dict] = []
    failures: list[dict] = []
    for ordinal in range(1, 32):
        source_dir = game_dirs.get(ordinal)
        if not source_dir:
            failures.append({"ordinal": ordinal, "reason": "No completed game folder was uploaded"})
            continue
        destination = root / source_dir.name
        shutil.copytree(source_dir, destination, dirs_exist_ok=True)
        manifests = list(destination.glob("manifest_*.json"))
        if not manifests:
            failures.append({"ordinal": ordinal, "reason": "Missing game manifest"})
            continue
        manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
        sheets = list(destination.glob("contact_sheet_*.jpg"))
        entries.append({
            "ordinal": ordinal,
            "game": manifest.get("game", destination.name),
            "selected_count": int(manifest.get("selected_count", 0)),
            "target_count": int(manifest.get("target_count", 15)),
            "source": manifest.get("source", {}),
            "folder": destination.name,
            "contact_sheet": str(sheets[0]) if sheets else None,
        })

    entries.sort(key=lambda item: item["ordinal"])
    total_images = sum(item["selected_count"] for item in entries)
    incomplete = [
        {"ordinal": item["ordinal"], "game": item["game"], "selected_count": item["selected_count"]}
        for item in entries if item["selected_count"] < item["target_count"]
    ]
    master = {
        "requested_games": 31,
        "completed_games": len(entries),
        "failed_games": len(failures),
        "target_per_game": 15,
        "selected_images": total_images,
        "expected_images_if_complete": 465,
        "complete_at_target": len(entries) == 31 and not incomplete,
        "collection_method": "Frames extracted from title-matched public gameplay videos; no unrestricted image-search scraping.",
        "validation_note": "Technical filtering and visual deduplication were automated. Contact sheets are included for final human visual approval.",
        "games": entries,
        "incomplete_games": incomplete,
        "failures": failures,
    }
    (root / "master_manifest.json").write_text(json.dumps(master, ensure_ascii=False, indent=2), encoding="utf-8")
    (root / "failed_games.json").write_text(json.dumps(failures, ensure_ascii=False, indent=2), encoding="utf-8")
    make_master_sheet(entries, root / "MASTER_CONTACT_SHEET.jpg")

    readme = f"""# AI Prod Gameplay Screenshot Reference Bank

## Result

- Requested games: 31
- Completed game folders: {len(entries)}
- Selected screenshots: {total_images} / 465
- Games below 15 images: {len(incomplete)}
- Failed game jobs: {len(failures)}

## Safety and sourcing

This pack does not use blind Google Images harvesting. Each folder was built from a public gameplay video whose title matched the requested game/version. Candidate frames were screened for basic technical quality, deduplicated with perceptual hashes and colour histograms, and selected for visual diversity.

Every game folder contains its source URL, title and channel in a JSON manifest, plus a numbered contact sheet. Automated screening cannot certify artistic usefulness or every edge case; inspect the contact sheets before adding frames to a permanent production library.
"""
    (root / "README.md").write_text(readme, encoding="utf-8")

    archive = shutil.make_archive(
        str(final_parent.parent / "AI_PROD_GAMEPLAY_REFERENCE_BANK"),
        "zip",
        final_parent,
        "GAMEPLAY_REFERENCE_BANK",
    )
    print(json.dumps(master, ensure_ascii=False, indent=2))
    print(f"ARCHIVE={archive}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
