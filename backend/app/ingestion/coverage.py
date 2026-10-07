"""What time span does this statement actually cover?

The matcher must never say "Not found" for a payment the statement could not
possibly contain yet. These helpers give it the facts.

compute_coverage      -> (start, end) of the statement
position_in_coverage  -> where a claim's timestamp sits relative to that span
"""

from __future__ import annotations

import datetime as dt
from typing import Optional, Sequence, Tuple


def compute_coverage(
    datetimes: Sequence[dt.datetime], has_time_of_day: bool
) -> Tuple[Optional[dt.datetime], Optional[dt.datetime]]:
    """First and last moment covered.

    If the statement only has dates (no times), the last day is covered until
    23:59:59, otherwise a payment made that evening would look 'after' it.
    """
    if not datetimes:
        return None, None
    start, end = min(datetimes), max(datetimes)
    if not has_time_of_day:
        start = dt.datetime.combine(start.date(), dt.time(0, 0, 0))
        end = dt.datetime.combine(end.date(), dt.time(23, 59, 59))
    return start, end


def position_in_coverage(
    ts: dt.datetime,
    start: Optional[dt.datetime],
    end: Optional[dt.datetime],
    settle_buffer: dt.timedelta = dt.timedelta(hours=24),
) -> str:
    """Where a claim time falls:

    'before'    earlier than the statement starts  -> "Can't verify yet" (wrong statement)
    'after'     later than the statement ends      -> "Can't verify yet" (re-check later)
    'near_end'  inside, but within ``settle_buffer`` of the end: the credit may
                simply not have posted yet          -> "Can't verify yet"
    'inside'    comfortably covered                 -> a missing credit may be "Not found"
    'unknown'   the statement has no usable dates
    """
    if start is None or end is None:
        return "unknown"
    if ts < start:
        return "before"
    if ts > end:
        return "after"
    if ts > end - settle_buffer:
        return "near_end"
    return "inside"