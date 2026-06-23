"""
FastAPI application for the Lot Tracking service.

Routes are intentionally thin: parse/validate the request (Pydantic
does this for us automatically), call into the store and rule engine,
shape the response. All the actual logic lives in store.py (data
access) and rules.py (domain calculations) - this file just wires
HTTP to those two layers. Keeping routes thin like this is what makes
the eventual MySQL swap-in (Day 3) and even a future language port
(e.g. to Laravel) easier: the interesting logic isn't tangled into
the HTTP layer.
"""

from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException

from .schemas import (
    CreateLotRequest,
    RecordEventRequest,
    LotResponse,
    EventResponse,
    DurationBreakdown,
)
from .store import store, LotNotFoundError
from .rules import (
    time_by_step,
    time_by_equipment,
    time_by_state,
    hold_reason_counts,
    is_stuck,
)

app = FastAPI(
    title="Lot Tracking Service",
    description="MES-style wafer lot tracking: step, equipment, and state as independent dimensions.",
    version="0.1.0",
)


def _to_lot_response(lot_id: str) -> LotResponse:
    """Shared helper: build a LotResponse from current store state."""
    lot = store.get_lot(lot_id)
    since = store.last_event_timestamp(lot_id)
    now = datetime.now(timezone.utc)
    seconds_in_state = (now - since).total_seconds()
    stuck = is_stuck(
        current_step=lot.current_step,
        current_state=lot.current_state,
        since=since,
        now=now,
    )
    return LotResponse(
        lot_id=lot.lot_id,
        wafer_count=lot.wafer_count,
        current_step=lot.current_step,
        current_eqp_id=lot.current_eqp_id,
        current_state=lot.current_state,
        since=since,
        seconds_in_current_state=seconds_in_state,
        is_stuck=stuck,
    )


@app.get("/health")
def health_check() -> dict[str, str]:
    """Liveness check - standard practice for any deployed service."""
    return {"status": "ok"}


@app.post("/lots", response_model=LotResponse, status_code=201)
def create_lot(request: CreateLotRequest) -> LotResponse:
    """Create a new lot, entering at a given step and equipment, state=WAITING."""
    if request.lot_id in store._lots:  # simple existence check for Day 2
        raise HTTPException(status_code=409, detail=f"Lot {request.lot_id} already exists")

    store.create_lot(
        lot_id=request.lot_id,
        wafer_count=request.wafer_count,
        step_id=request.step_id,
        eqp_id=request.eqp_id,
    )
    return _to_lot_response(request.lot_id)


@app.get("/lots/{lot_id}", response_model=LotResponse)
def get_lot_status(lot_id: str) -> LotResponse:
    """Get a lot's current snapshot: step, equipment, state, and how long it's been there."""
    try:
        return _to_lot_response(lot_id)
    except LotNotFoundError:
        raise HTTPException(status_code=404, detail=f"Lot {lot_id} not found")


@app.post("/lots/{lot_id}/events", response_model=EventResponse, status_code=201)
def record_event(lot_id: str, request: RecordEventRequest) -> EventResponse:
    """Record a change in step, equipment, and/or state for a lot."""
    try:
        event = store.record_event(
            lot_id=lot_id,
            step_id=request.step_id,
            eqp_id=request.eqp_id,
            state=request.state,
            hold_reason=request.hold_reason,
        )
    except LotNotFoundError:
        raise HTTPException(status_code=404, detail=f"Lot {lot_id} not found")

    return EventResponse(
        event_id=event.event_id,
        lot_id=event.lot_id,
        step_id=event.step_id,
        eqp_id=event.eqp_id,
        state=event.state,
        hold_reason=event.hold_reason,
        timestamp=event.timestamp,
    )


@app.get("/lots/{lot_id}/breakdown/by-step", response_model=DurationBreakdown)
def get_breakdown_by_step(lot_id: str) -> DurationBreakdown:
    """How much total time this lot has spent at each process step."""
    try:
        events = store.get_events(lot_id)
    except LotNotFoundError:
        raise HTTPException(status_code=404, detail=f"Lot {lot_id} not found")

    now = datetime.now(timezone.utc)
    totals = time_by_step(events, as_of=now)
    return DurationBreakdown(
        breakdown={step.value: dur.total_seconds() for step, dur in totals.items()}
    )


@app.get("/lots/{lot_id}/breakdown/by-equipment", response_model=DurationBreakdown)
def get_breakdown_by_equipment(lot_id: str) -> DurationBreakdown:
    """How much total time this lot has spent on each piece of equipment."""
    try:
        events = store.get_events(lot_id)
    except LotNotFoundError:
        raise HTTPException(status_code=404, detail=f"Lot {lot_id} not found")

    now = datetime.now(timezone.utc)
    totals = time_by_equipment(events, as_of=now)
    return DurationBreakdown(breakdown={eqp: dur.total_seconds() for eqp, dur in totals.items()})


@app.get("/lots/{lot_id}/breakdown/by-state", response_model=DurationBreakdown)
def get_breakdown_by_state(lot_id: str) -> DurationBreakdown:
    """How much total time this lot has spent in each state (WAITING, PROCESSING, HOLD, ...)."""
    try:
        events = store.get_events(lot_id)
    except LotNotFoundError:
        raise HTTPException(status_code=404, detail=f"Lot {lot_id} not found")

    now = datetime.now(timezone.utc)
    totals = time_by_state(events, as_of=now)
    return DurationBreakdown(
        breakdown={state.value: dur.total_seconds() for state, dur in totals.items()}
    )


@app.get("/lots/{lot_id}/holds")
def get_hold_reasons(lot_id: str) -> dict[str, int]:
    """Count of how many times each hold reason has occurred for this lot."""
    try:
        events = store.get_events(lot_id)
    except LotNotFoundError:
        raise HTTPException(status_code=404, detail=f"Lot {lot_id} not found")

    counts = hold_reason_counts(events)
    return {reason.value: count for reason, count in counts.items()}
