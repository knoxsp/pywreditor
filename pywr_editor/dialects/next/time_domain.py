import re
from datetime import datetime, timedelta
from typing import Any

"""
 The "time" section of a pywr-next model: the first and last date of the run, and the
 timestep, which is a number of days, a number of hours or a frequency such as "7d".
 Dates are written as "2015-01-31" or with a time, "2015-01-31T06:00:00".
 No Qt in this module.
"""

TIMESTEP_TYPES = ("Days", "Hours", "Frequency")
""" The types of timestep of the schema, with their values in "days", "hours" and
"freq" """
ISO_SPAN = re.compile(
    r"^P(?=\d|T)(?:\d+Y)?(?:\d+M)?(?:\d+W)?(?:\d+D)?(?:T(?:\d+H)?(?:\d+M)?(?:\d+S)?)?$",
    re.I,
)
""" A span in the ISO 8601 form, such as "P7D" or "PT6H" """
FRIENDLY_UNITS = {
    "y", "yr", "yrs", "year", "years", "mo", "mos", "month", "months", "w", "wk",
    "wks", "week", "weeks", "d", "day", "days", "h", "hr", "hrs", "hour", "hours",
    "m", "min", "mins", "minute", "minutes", "s", "sec", "secs", "second", "seconds",
}  # fmt: skip
""" The units of the "friendly" form that pywr-next reads, such as "7d" or "1 month" """
DATE_FORMATS = (
    "%Y-%m-%d",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
)


def is_frequency(text: str) -> bool:
    """
    Checks whether a text looks like a span that pywr-next reads: the ISO form ("P7D")
    or the friendly form ("7d", "1 month", "1w 2d").
    :param text: The text.
    :return: True if the text is a valid span.
    """
    text = text.strip()
    if ISO_SPAN.match(text):
        return True
    parts = re.findall(r"(\d+)\s*([A-Za-z]+)", text)
    remaining = re.sub(r"(\d+)\s*([A-Za-z]+)|,|\s", "", text, flags=re.I)
    return bool(parts) and not remaining and all(
        unit.lower() in FRIENDLY_UNITS for _, unit in parts
    )


def parse_time(text: Any) -> datetime | None:
    """
    Reads a start or end date.
    :param text: The text, "2015-01-31" or "2015-01-31T06:00:00".
    :return: The date, None if it is not a valid date.
    """
    if not isinstance(text, str):
        return None
    text = text.strip()
    for date_format in DATE_FORMATS:
        try:
            return datetime.strptime(text, date_format)
        except ValueError:
            continue
    return None


def has_time_of_day(text: Any) -> bool:
    """
    Checks whether a date has a time.
    :param text: The date text.
    :return: True for "2015-01-31T06:00:00", False for "2015-01-31" or an invalid date.
    """
    return isinstance(text, str) and "T" in text and parse_time(text) is not None


def timestep_type(timestep: Any) -> str | None:
    """
    Returns the type of a timestep.
    :param timestep: The "timestep" dictionary.
    :return: "Days", "Hours" or "Frequency", None if it is not valid.
    """
    if isinstance(timestep, dict) and timestep.get("type") in TIMESTEP_TYPES:
        return timestep["type"]
    return None


def timestep_value(timestep: dict) -> Any:
    """
    Returns the number of days or hours, or the frequency of a timestep.
    :param timestep: The "timestep" dictionary.
    :return: The value.
    """
    key = {"Days": "days", "Hours": "hours", "Frequency": "freq"}.get(
        timestep_type(timestep) or ""
    )
    return timestep.get(key) if key else None


def make_timestep(kind: str, value: Any) -> dict:
    """
    Builds the "timestep" dictionary.
    :param kind: "Days", "Hours" or "Frequency".
    :param value: The number of days or hours, or the frequency.
    :return: The dictionary.
    """
    key = {"Days": "days", "Hours": "hours", "Frequency": "freq"}[kind]
    return {"type": kind, key: value}


def describe_timestep(timestep: Any) -> str:
    """
    Describes a timestep for the user.
    :param timestep: The "timestep" dictionary.
    :return: The text, such as "7 days".
    """
    kind = timestep_type(timestep)
    value = timestep_value(timestep) if kind else None
    if kind == "Days" and isinstance(value, int):
        return f"{value} day" + ("" if value == 1 else "s")
    if kind == "Hours" and isinstance(value, int):
        return f"{value} hour" + ("" if value == 1 else "s")
    if kind == "Frequency" and isinstance(value, str):
        return f"every {value}"
    return "not set"


def step_length(timestep: Any) -> timedelta | None:
    """
    Returns the length of a timestep, when it is fixed.
    :param timestep: The "timestep" dictionary.
    :return: The length, None for a frequency (which may be a month, for example) or
    an invalid timestep.
    """
    kind = timestep_type(timestep)
    value = timestep_value(timestep) if kind else None
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        return None
    if kind == "Days":
        return timedelta(days=value)
    if kind == "Hours":
        return timedelta(hours=value)
    return None


def count_steps(time: dict) -> int | None:
    """
    Counts the timesteps of a run.
    :param time: The "time" dictionary.
    :return: The number of timesteps, None if it cannot be known (a frequency, or
    invalid dates).
    """
    start, end = parse_time(time.get("start")), parse_time(time.get("end"))
    length = step_length(time.get("timestep"))
    if start is None or end is None or length is None or end < start:
        return None
    return int((end - start) / length) + 1


def validate_time(time: Any) -> list[str]:
    """
    Checks the "time" section.
    :param time: The "time" dictionary.
    :return: The problems found, as sentences. An empty list if it is valid.
    """
    if not isinstance(time, dict):
        return ["The time section is missing"]
    problems = []
    start, end = parse_time(time.get("start")), parse_time(time.get("end"))
    for label, date, value in (
        ("start", start, time.get("start")),
        ("end", end, time.get("end")),
    ):
        if date is None:
            problems.append(
                f"The {label} date {value!r} is not valid: write it as "
                "2015-01-31 or 2015-01-31T06:00:00"
                if value
                else f"The {label} date is required"
            )
    if start is not None and end is not None and end < start:
        problems.append("The end date is before the start date")

    timestep = time.get("timestep")
    kind = timestep_type(timestep)
    value = timestep_value(timestep) if kind else None
    if kind is None:
        problems.append("The timestep must be days, hours or a frequency")
    elif kind == "Frequency":
        if not isinstance(value, str) or not value.strip():
            problems.append("The frequency is required, such as 7d")
        elif not is_frequency(value):
            problems.append(
                f"The frequency {value!r} is not recognised: write it like 7d, "
                "1 month or P7D"
            )
    elif not isinstance(value, int) or isinstance(value, bool) or value < 1:
        problems.append(f"The number of {kind.lower()} must be a whole number above 0")
    return problems
