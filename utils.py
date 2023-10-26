from typing import Optional
from datetime import datetime

from config import Config


def parse_time(time: str) -> Optional[datetime]:
    for time_format in Config.POSSIBLE_FORMATS:
        try:
            return datetime.strptime(time, time_format)
        except Exception:
            continue

    return None
