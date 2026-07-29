"""Regression contract for importing the deprecated workforce router stack."""

from __future__ import annotations

import importlib


def test_legacy_workforce_repository_imports_on_supported_python() -> None:
    module = importlib.import_module("app.workforce.repository")

    assert module.SvarshchikRepo.__name__ == "SvarshchikRepo"

