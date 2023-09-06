import pytest

# Standard library imports...
from unittest.mock import Mock, patch

from kubernetes.client.models import *

import k8soptimizer.helpers as helpers

__author__ = "Philipp Hellmich"
__copyright__ = "Philipp Hellmich"
__license__ = "MIT"


def test_convert_to_bytes():
    assert helpers.convert_to_bytes("1B") == 1
    assert helpers.convert_to_bytes("1K") == 1024
    assert helpers.convert_to_bytes("1M") == 1024**2
    assert helpers.convert_to_bytes("1G") == 1024**3
    assert helpers.convert_to_bytes("1T") == 1024**4
    assert helpers.convert_to_bytes("1Ki") == 1024
    assert helpers.convert_to_bytes("1Mi") == 1024**2
    assert helpers.convert_to_bytes("1Gi") == 1024**3
    assert helpers.convert_to_bytes("1Ti") == 1024**4

    with pytest.raises(ValueError) as exc_info:
        result = helpers.convert_to_bytes("hallo")
    assert str(exc_info.value) == "Invalid format"

    with pytest.raises(ValueError) as exc_info:
        result = helpers.convert_to_bytes("1Jon")
    assert str(exc_info.value) == "Invalid unit"


def test_convert_to_number():
    assert helpers.convert_to_number("1000m") == 1
    assert helpers.convert_to_number("1000k") == 1000000

    with pytest.raises(ValueError) as exc_info:
        result = helpers.convert_to_number("1z")
    assert str(exc_info.value) == "Invalid unit"


def test_format_pairs():
    assert helpers.format_pairs({"name": "otto"}) == "name=otto"
    assert helpers.format_pairs({"name": "otto", "age": 6}) == "name=otto, age=6"


def test_calculate_minutes_ago():
    assert (
        helpers.calculate_minutes_ago_from_timestamp("2022-07-13T11:46:45Z")
        > 60 * 24 * 365
    )
    assert (
        helpers.calculate_minutes_ago_from_timestamp("2012-07-13T11:46:45Z")
        > 60 * 24 * 365 * 10
    )
    assert helpers.calculate_minutes_ago_from_timestamp("2050-07-13T11:46:45Z") < 0

def test_create_timestamp_str():
    assert len(helpers.create_timestamp_str()) == 69
    assert helpers.calculate_minutes_ago_from_timestamp(helpers.create_timestamp_str()) == 0
