"""Smoke test: package imports cleanly. Replace/extend as modules land."""

import datamold


def test_version_is_set() -> None:
    assert datamold.__version__
