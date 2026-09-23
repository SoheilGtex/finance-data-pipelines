from __future__ import annotations

import os
import signal
import sys
from pathlib import Path

from fdp.extract import generate_synthetic
from fdp.strategies import incremental_upsert


def kill_before_commit(stage: str) -> None:
    if stage == "before_commit":
        os.kill(os.getpid(), signal.SIGKILL)


if __name__ == "__main__":
    incremental_upsert(
        generate_synthetic(rows=30, seed=4),
        database_path=Path(sys.argv[1]),
        fault_hook=kill_before_commit,
    )
