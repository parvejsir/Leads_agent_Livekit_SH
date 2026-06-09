# app/core/logging.py

import logging


logging.basicConfig(

    level=logging.INFO,

    format=

    "%(asctime)s | %(levelname)s | %(message)s"

)


LOGGER = logging.getLogger(
    "VOICE_AGENT"
)