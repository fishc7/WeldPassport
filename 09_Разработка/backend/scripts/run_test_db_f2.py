"""Thin CLI for the separately authorized TEST-DB-F2 rehearsal."""

from __future__ import annotations

import json
import os

from app.testing.f2_contract import F2MachineStatus
from app.testing.f2_coordinator import run_f2


def main() -> int:
    result = run_f2(os.environ)
    print(
        json.dumps(
            {
                "run_id": (
                    None if result.run_id is None else str(result.run_id)
                ),
                "status": result.status.value,
                "manifest_digest": result.manifest_digest,
            },
            sort_keys=True,
        )
    )
    return (
        0
        if result.status is F2MachineStatus.REHEARSAL_VERIFIED
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
