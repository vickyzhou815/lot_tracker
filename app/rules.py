"""
Rule engine for the Lot Tracking service.

This module takes a lot's full history of LotEvents and computes
derived facts, sliced along each of the three independent dimensions
(step, equipment, state): time spent per step, time spent per piece
of equipment, hold-reason counts, and whether the lot is currently
"stuck" given its current step/state combination. No database, no
API - pure functions over data, which makes this the easiest part of
the whole project to unit test.
"""

from collections import Counter, defaultdict
from datetime import datetime, timedelta

from .models import LotEvent, ProcessStep, LotState, HoldReason, TERMINAL_STATES

# How long a lot can sit in PROCESSING at a given step before we
# consider it "stuck". In a real fab this would come from a process
# spec or engineering cycle-time target; here we hardcode reasonable
# defaults so the rule engine has something concrete to check.
# Time spent WAITING or on HOLD is not compared against this - those
# are tracked separately, since "stuck while waiting" and "stuck
# while processing" point to different root causes.
PROCESSING_TIME_LIMITS: dict[ProcessStep, timedelta] = {
    ProcessStep.LITHOGRAPHY: timedelta(hours=2),
    ProcessStep.ETCH: timedelta(hours=1, minutes=30),
    ProcessStep.DEPOSITION: timedelta(hours=3),
    ProcessStep.INSPECTION: timedelta(minutes=45),
}

# A lot shouldn't sit on HOLD indefinitely without someone looking at it.
HOLD_TIME_LIMIT = timedelta(hours=1)


def _span_durations(
    events: list[LotEvent],
    key_fn,
    as_of: datetime,
) -> dict:
    """
    Shared helper: walk consecutive event pairs and accumulate the
    duration of each span under whatever key `key_fn(event)` returns.
    Used for step/equipment/state breakdowns below so we don't repeat
    the same "walk pairs, close the last span at as_of" logic three
    times - similar in spirit to a small template function in C++.
    """
    events_sorted = sorted(events, key=lambda e: e.timestamp)
    totals: dict = defaultdict(timedelta)

    for i, evt in enumerate(events_sorted):
        span_start = evt.timestamp
        span_end = (
            events_sorted[i + 1].timestamp
            if i + 1 < len(events_sorted)
            else as_of
        )
        totals[key_fn(evt)] += span_end - span_start

    return dict(totals)


def time_by_step(events: list[LotEvent], as_of: datetime) -> dict[ProcessStep, timedelta]:
    """Total time spent at each process step, across all visits and states."""
    return _span_durations(events, key_fn=lambda e: e.step_id, as_of=as_of)


def time_by_equipment(events: list[LotEvent], as_of: datetime) -> dict[str, timedelta]:
    """Total time spent on each piece of equipment, across all visits and steps."""
    return _span_durations(events, key_fn=lambda e: e.eqp_id, as_of=as_of)


def time_by_state(events: list[LotEvent], as_of: datetime) -> dict[LotState, timedelta]:
    """Total time spent in each state (WAITING, PROCESSING, HOLD, ...)."""
    return _span_durations(events, key_fn=lambda e: e.state, as_of=as_of)


def hold_reason_counts(events: list[LotEvent]) -> Counter:
    """
    Count how many times each HoldReason occurred.

    Counter is a dict subclass from the standard library - similar
    in spirit to std::map<HoldReason, int> but with built-in helpers
    like .most_common(). Cheap and idiomatic for this kind of tally.
    """
    return Counter(
        evt.hold_reason for evt in events
        if evt.hold_reason is not None
    )


def is_stuck(
    current_step: ProcessStep,
    current_state: LotState,
    since: datetime,
    now: datetime,
) -> bool:
    """
    Return True if the lot has been in its current (step, state)
    combination longer than what we consider normal.

    Terminal states (SCRAPPED, COMPLETED) are never "stuck" - the
    lot's lifecycle is over, there's nothing further to wait on.
    HOLD is checked against a single flat HOLD_TIME_LIMIT regardless
    of step, since an open hold is an operations concern independent
    of which step it happened at. PROCESSING is checked against the
    step-specific PROCESSING_TIME_LIMITS table. WAITING has no limit
    defined here - queue time alone isn't flagged as a problem by
    this simplified rule engine.
    """
    if current_state in TERMINAL_STATES:
        return False

    elapsed = now - since

    if current_state == LotState.HOLD:
        return elapsed > HOLD_TIME_LIMIT

    if current_state == LotState.PROCESSING:
        limit = PROCESSING_TIME_LIMITS.get(current_step)
        return limit is not None and elapsed > limit

    return False
