import re


def convert_to_bytes(size_str):
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
    match = re.match(pattern, size_str)

    if match:
        value = float(match.group(1))
        unit = match.group(3)
    else:
        raise ValueError("Invalid format")

    if unit not in units:
        raise ValueError("Invalid unit")

    bytes_value = value * units[unit]
    return int(bytes_value)


def convert_to_number(value_str):
    units = {"m": 1 / 1000, "k": 1000}

    value_str = value_str.strip()
    unit = value_str[-1]
    value = float(value_str[:-1])

    if unit not in units:
        raise ValueError("Invalid unit")

    number_value = value * units[unit]
    return round(number_value)


def format_pairs(value_array):
    formatted_pairs = []
    for key, value in value_array.items():
        formatted_pairs.append(f"{key}={value}")
    return ", ".join(formatted_pairs)
