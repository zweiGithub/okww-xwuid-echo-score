"""Shared validation for the host's integer millisecond control."""

READ_INTERVAL_KEY = '读取间隔（毫秒）'
DEFAULT_READ_INTERVAL_MS = 1000
# QSpinBox stores its range/value as a signed native int.
MAX_READ_INTERVAL_MS = 2147483647


def validate_read_interval(value):
    if type(value) is not int or not 1 <= value <= MAX_READ_INTERVAL_MS:
        return f'读取间隔须为 1 至 {MAX_READ_INTERVAL_MS} 的整数毫秒'
    return None


def read_interval_seconds(value):
    milliseconds = value if validate_read_interval(value) is None else DEFAULT_READ_INTERVAL_MS
    return milliseconds / 1000
