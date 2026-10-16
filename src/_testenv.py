"""Shared bootstrap for every headless test in this folder.

    import _testenv          # FIRST, before importing room_overlay
    import room_overlay as R

Points BUG_SAVE at a throwaway temp file so a test can never read or write the
player's live save (%LOCALAPPDATA%\\bug_pet\\save.json).

This matters: test_logic.py drives a real mating, and the mating lays an egg.
Without isolation it overwrites whatever offspring the player was growing --
a 成长期 pet silently restarts as 卵期.  room_overlay._save_game() now refuses
such a write as a second line of defence, but tests should still isolate.
"""
import os
import tempfile

if not os.environ.get("BUG_SAVE"):
    os.environ["BUG_SAVE"] = os.path.join(
        tempfile.mkdtemp(prefix="bugpet_test_"), "save.json")
