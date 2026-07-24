#!/usr/bin/env python3
"""Run the auto-frame harvester with targeted fallback queries."""

from __future__ import annotations

import harvest_game_screenshots as base

# These niche titles returned too few exact matches for the stricter first-pass
# searches. Keep their exact aliases and sequel exclusions, but use wording that
# surfaces episodic walkthrough and longplay uploads.
base.GAMES[7]["query"] = "Ghost Trick Phantom Detective DS walkthrough part 1 gameplay"
base.GAMES[8]["query"] = "Fantasy Life Nintendo 3DS walkthrough part 1 gameplay"
base.GAMES[19]["query"] = "Auto Modellista PS2 longplay full game gameplay"

import harvest_youtube_auto_frames as harvester  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(harvester.main())
