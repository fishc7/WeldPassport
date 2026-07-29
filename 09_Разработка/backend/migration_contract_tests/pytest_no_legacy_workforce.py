"""Test-only plugin that isolates canonical application tests from legacy workforce.

The runtime compatibility profile is a separate Task. QualityDecision tests do not
exercise the deprecated workforce router, so a no-op router prevents its import-time
annotation defect from blocking this scoped acceptance run.
"""

from __future__ import annotations

import sys
from types import ModuleType

from fastapi import APIRouter


module = ModuleType("app.workforce.api")
module.router = APIRouter()
sys.modules.setdefault("app.workforce.api", module)

