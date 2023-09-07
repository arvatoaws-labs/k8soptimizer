from datetime import datetime, timedelta, timezone

import pytest

import k8soptimizer.helpers as helpers

__author__ = "Philipp Hellmich"
__copyright__ = "Philipp Hellmich"
__license__ = "MIT"


def test_convert_memory_request_to_bytes():
    assert helpers.convert_memory_request_to_bytes("1B") == 1
    assert helpers.convert_memory_request_to_bytes("1K") == 1024
    assert helpers.convert_memory_request_to_bytes("1M") == 1024**2
    assert helpers.convert_memory_request_to_bytes("1G") == 1024**3
    assert helpers.convert_memory_request_to_bytes("1T") == 1024**4
    assert helpers.convert_memory_request_to_bytes("1Ki") == 1024
    assert helpers.convert_memory_request_to_bytes("1Mi") == 1024**2
    assert helpers.convert_memory_request_to_bytes("1Gi") == 1024**3
    assert helpers.convert_memory_request_to_bytes("1Ti") == 1024**4

    with pytest.raises(ValueError) as exc_info:
        helpers.convert_memory_request_to_bytes("hallo")
    assert str(exc_info.value).startswith("Invalid format")

    with pytest.raises(ValueError) as exc_info:
        helpers.convert_memory_request_to_bytes("1Jon")
    assert str(exc_info.value).startswith("Invalid unit")


def test_convert_cpu_request_to_cores():
    assert helpers.convert_cpu_request_to_cores("1000m") == 1
    assert helpers.convert_cpu_request_to_cores("1000k") == 1000000
    assert helpers.convert_cpu_request_to_cores("1") == 1

    with pytest.raises(ValueError) as exc_info:
        helpers.convert_cpu_request_to_cores("1z")
    assert str(exc_info.value).startswith("Invalid unit")

    with pytest.raises(ValueError) as exc_info:
        helpers.convert_cpu_request_to_cores("OTTO")
    assert str(exc_info.value).startswith("Invalid format")


def test_format_pairs():
    assert helpers.format_pairs({"name": "otto"}) == "name=otto"
    assert helpers.format_pairs({"name": "otto", "age": 6}) == "name=otto, age=6"


def test_calculate_minutes_ago():
    # Create datetime objects from timestamp strings
    timestamp1 = datetime.now(timezone.utc) - timedelta(days=1)
    timestamp2 = datetime.now(timezone.utc) - timedelta(minutes=15)
    timestamp3 = datetime.now(timezone.utc)

    # Use the calculate_minutes_ago_from_timestamp function
    assert helpers.calculate_minutes_ago_from_timestamp(timestamp1) == 60 * 24
    assert helpers.calculate_minutes_ago_from_timestamp(timestamp2) == 15
    assert helpers.calculate_minutes_ago_from_timestamp(timestamp3) == 0


def test_create_timestamp_str():
    assert helpers.calculate_minutes_ago_from_timestamp(helpers.create_timestamp()) == 0
