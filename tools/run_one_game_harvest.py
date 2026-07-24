#!/usr/bin/env python3
"""Run one indexed game through the main screenshot harvester."""

from __future__ import annotations

import os
import sys

import harvest_game_screenshots as harvester


def main() -> int:
    raw_index = os.environ.get("GAME_INDEX", "").strip()
    if not raw_index:
        raise SystemExit("GAME_INDEX is required")
    index = int(raw_index)
    if not 1 <= index <= len(harvester.GAMES):
        raise SystemExit(f"GAME_INDEX must be between 1 and {len(harvester.GAMES)}")

    selected_game = harvester.GAMES[index - 1]
    original_process_game = harvester.process_game

    # Retain the original global ordinal in the output folder while making the
    # existing main routine process only this single game.
    harvester.GAMES = [selected_game]
    harvester.process_game = lambda game, _ordinal: original_process_game(game, index)
    harvester.make_master_contact_sheet = lambda _manifests, _destination: None
    return harvester.main()


if __name__ == "__main__":
    sys.exit(main())
