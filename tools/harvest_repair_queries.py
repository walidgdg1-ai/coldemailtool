#!/usr/bin/env python3
"""Run the auto-frame harvester with targeted fallback queries."""

from __future__ import annotations

import harvest_game_screenshots as base

# These two older/niche titles returned only sequel/review-heavy results for the
# stricter first-pass searches. Keep exact game aliases and sequel exclusions,
# but use search wording that surfaces episodic gameplay uploads.
base.GAMES[8]["query"] = "Fantasy Life Nintendo 3DS walkthrough part 1 gameplay"
base.GAMES[19]["query"] = "Auto Modellista PS2 longplay full game gameplay"

import harvest_youtube_auto_frames as harvester  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(harvester.main())
