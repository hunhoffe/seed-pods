from __future__ import annotations
import logging
import sys

logging.basicConfig(
    level=logging.DEBUG,
    format='%(name)s - %(levelname)s - %(message)s',
    handlers = [logging.StreamHandler(stream=sys.stderr)]
)

def get_logger(name: str) -> Logger:
    return logging.getLogger(name)
