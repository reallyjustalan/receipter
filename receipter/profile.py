"""Shared python-escpos configuration for the TM-U220A variant."""
from copy import deepcopy
import os

from escpos.capabilities import Profile, get_profile

PROFILE_NAME = os.getenv("PRINTER_PROFILE", "TM-U220B")
if PROFILE_NAME not in ("TM-U220", "TM-U220B"):
    raise ValueError("PRINTER_PROFILE must be TM-U220 or TM-U220B")
MODEL_NAME = "TM-U220A"


def printer_profile() -> Profile:
    # B has partial-cut support built in. The family profile disables cutters;
    # enable partial cutting there for the user's reported A hardware as well.
    # These profiles produce identical ASCII text and partial-cut bytes.
    # Copy the profile so this override never mutates the library database.
    data = deepcopy(get_profile(PROFILE_NAME).profile_data)
    data["features"]["paperPartCut"] = True
    profile = Profile(features=data["features"])
    profile.profile_data = data
    return profile
