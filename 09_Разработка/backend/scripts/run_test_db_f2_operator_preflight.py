"""Thin CLI for offline TEST-DB-F2 operator preflight."""

from __future__ import annotations

import json
import os
from typing import Mapping

from app.testing.f2_operator_preflight import (
    F2OperatorPreflightStatus,
    OperatorPreflightDependencies,
    run_operator_preflight,
)


def main(
    *,
    environment: Mapping[str, str] | None = None,
    dependencies: OperatorPreflightDependencies | None = None,
) -> int:
    result = run_operator_preflight(
        os.environ if environment is None else environment,
        dependencies,
    )
    print(
        json.dumps(
            {
                "artifact_digest": result.artifact_digest,
                "preflight_id": (
                    None
                    if result.preflight_id is None
                    else str(result.preflight_id)
                ),
                "status": result.status.value,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return (
        0
        if result.status is F2OperatorPreflightStatus.READY
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
