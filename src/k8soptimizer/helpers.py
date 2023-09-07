import re
import datetime
from datetime import datetime, timezone, timedelta
from dateutil import parser
from beartype import beartype


@beartype
def convert_memory_request_to_bytes(size: str) -> int:
    units = {
        "B": 1,
        "K": 1024,
        "M": 1024**2,
        "G": 1024**3,
        "T": 1024**4,
        "Ki": 1024,
        "Mi": 1024**2,
        "Gi": 1024**3,
        "Ti": 1024**4,
    }

    pattern = r"(\d+(\.\d+)?)\s*([a-zA-Z]+)"
    match = re.match(pattern, size)

    if match:
        value = float(match.group(1))
        unit = match.group(3)
    else:
        raise ValueError("Invalid format")

    if unit not in units:
        raise ValueError("Invalid unit")

    bytes_value = value * units[unit]
    return int(bytes_value)


@beartype
def convert_cpu_request_to_cores(size: str) -> float:
    units = {"m": 1 / 1000, "k": 1000}

    size = size.strip()
    unit = size[-1]
    value = float(size[:-1])

    if unit not in units:
        raise ValueError("Invalid unit")

    number_value = value * units[unit]
    return number_value


@beartype
def format_pairs(values: dict) -> str:
    formatted_pairs = []
    for key, value in values.items():
        formatted_pairs.append(f"{key}={value}")
    return ", ".join(formatted_pairs)


def create_timestamp():
    # n = datetime.now(datetime.timezone.utc)
    return datetime.now(timezone.utc)
    # return n.isoformat()  # '2021-07-13T15:28:51.818095+00:00'


@beartype
def calculate_minutes_ago_from_timestamp(datetime_object: datetime) -> int:
    current_time = datetime.now(timezone.utc)
    time_difference = current_time - datetime_object
    return int(time_difference.total_seconds() / 60)
