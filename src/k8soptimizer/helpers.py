import argparse
import re
from datetime import datetime, timezone

from beartype import beartype

__author__ = "Philipp Hellmich"
__copyright__ = "Arvato Systems GmbH"
__license__ = "MIT"


@beartype
def convert_memory_request_to_bytes(size: str) -> int:
    """
    Convert a memory size string to bytes.

    Args:
        size (str): The memory size string (e.g., '1Gi', '512M', '2.5Ki').

    Returns:
        int: The size in bytes.

    Raises:
        ValueError: If the input size has an invalid format or unit.

    Example:
        size_in_bytes = convert_memory_request_to_bytes('2Gi')
    """
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
        raise ValueError("Invalid format: {}".format(size))

    if unit not in units:
        raise ValueError("Invalid unit: {}".format(unit))

    bytes_value = value * units[unit]
    return int(bytes_value)


@beartype
def convert_cpu_request_to_cores(size: str) -> float:
    """
    Convert a CPU request size string to cores.

    Args:
        size (str): The CPU request size string (e.g., '500m', '1k', '0.5').

    Returns:
        float: The size in cores.

    Raises:
        ValueError: If the input size has an invalid format or unit.

    Example:
        cores = convert_cpu_request_to_cores('2.5k')
    """
    units = {"m": 1 / 1000, "k": 1000, "": 1}

    pattern = r"(\d+\.?\d?)(.*)?"
    match = re.match(pattern, size)

    if match:
        value = float(match.group(1))
        unit = match.group(2)
    else:
        raise ValueError("Invalid format: {}".format(size))

    if unit not in units:
        raise ValueError("Invalid unit: {}".format(unit))

    bytes_value = value * units[unit]
    return float(bytes_value)


@beartype
def format_pairs(values: dict) -> str:
    """
    Format a dictionary of key-value pairs into a comma-separated string.

    Args:
        values (dict): A dictionary containing key-value pairs.

    Returns:
        str: A string containing formatted key-value pairs, separated by commas.

    Example:
        formatted_string = format_pairs({"key1": "value1", "key2": "value2"})
    """
    formatted_pairs = []
    for key, value in values.items():
        formatted_pairs.append(f"{key}={value}")
    return ", ".join(formatted_pairs)


def create_timestamp():
    """
    Create a timestamp representing the current date and time in UTC.

    Returns:
        datetime: A datetime object representing the current UTC date and time.

    Example:
        timestamp = create_timestamp()
    """
    return datetime.now(timezone.utc)


@beartype
def calculate_minutes_ago_from_timestamp(datetime_object: datetime) -> int:
    """
    Calculate the number of minutes ago a given timestamp is from the current time.

    Args:
        datetime_object (datetime): The datetime object to calculate the minutes ago.

    Returns:
        int: The number of minutes ago.

    Example:
        timestamp = datetime(2023, 9, 7, 12, 0, tzinfo=timezone.utc)
        minutes_ago = calculate_minutes_ago_from_timestamp(timestamp)
    """
    current_time = datetime.now(timezone.utc)
    time_difference = current_time - datetime_object
    return int(time_difference.total_seconds() / 60)


@beartype
def calculate_minutes_ago_from_timestamp_str(timestamp: str) -> int:
    """
    Calculate the number of minutes ago a given timestamp is from the current time.

    Args:
        datetime_object (datetime): The datetime object to calculate the minutes ago.

    Returns:
        int: The number of minutes ago.

    Example:
        timestamp = '2023-09-11T09:04:50.539072+00:00'
        minutes_ago = calculate_minutes_ago_from_timestamp(timestamp)
    """
    datetime_object = datetime.fromisoformat(timestamp)
    return calculate_minutes_ago_from_timestamp(datetime_object)


@beartype
def is_valid_regex(value: str) -> bool:
    try:
        re.compile(value)
        return True
    except re.error:
        return False


@beartype
def valid_regex_arg(value: str) -> str:
    if is_valid_regex(value):
        return value
    raise argparse.ArgumentTypeError(f"'{value}' is not a valid regular expression")


@beartype
def is_valid_k8s_name(name: str) -> bool:
    # Check length
    if len(name) > 253:
        return False

    # Check pattern
    pattern = r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$"
    if bool(re.match(pattern, name)):
        return True
    return False


@beartype
def valid_k8s_name_arg(name: str) -> str:
    if is_valid_k8s_name(name):
        return name
    raise argparse.ArgumentTypeError(f"'{name}' is not a valid k8s object name")
