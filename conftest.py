"""Repo-wide test default: the existing suite exercises the sample basket, so it runs in demo mode.
Set at import so module-scoped fixtures see it. Tests of normal mode remove the variable themselves."""

import os

os.environ["OMNIBASKET_DEMO"] = "1"
