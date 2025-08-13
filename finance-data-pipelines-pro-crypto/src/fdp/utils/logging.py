from __future__ import annotations

import logging

def setup_logging(level: int = logging.INFO):
    logging.basicConfig(
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        level=level,
    )
    return logging.getLogger("fdp")
