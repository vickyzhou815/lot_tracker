"""
API-facing request/response schemas (Pydantic models).

Why a SEPARATE set of models from app/models.py?

app/models.py has our DOMAIN dataclasses - the internal representation
we reason about and test against. This file has API SCHEMAS - the
shape of JSON going in and out over HTTP. They often look similar,
but keeping them separate matters once a real system grows:
  - the API might want to hide internal fields (e.g. event_id),
    accept slightly different input than we store internally, or
    version the API independently of internal refactors
  - Pydantic gives us automatic request validation (FastAPI rejects
    a bad request with a clear 422 error before our code even runs)
    and automatic OpenAPI/Swagger docs generation - dataclasses don't
    do either of those on their own

C++ comparison: this is similar to having a DTO (data transfer
object) layer distinct from your internal domain objects - common in
larger C++ services too, just less automatic than Pydantic makes it.
"""

from datetime import datetime
from pydantic import BaseModel, Field

from .models import ProcessStep, LotState, HoldReason


class CreateLotRequest(BaseModel):
    """Body for POST /lots - create a new lot."""
    lot_id: str = Field(..., examples=["LOT-0042"])
    wafer_count: int = Field(..., gt=0, examples=[25])
    step_id: ProcessStep
    eqp_id: str = Field(..., examples=["EQP-01"])


class RecordEventRequest(BaseModel):
    """Body for POST /lots/{lot_id}/events - record a state/step/equipment change."""
    step_id: ProcessStep
    eqp_id: str
    state: LotState
    hold_reason: HoldReason | None = None


class LotResponse(BaseModel):
    """Response shape for a lot's current status."""
    lot_id: str
    wafer_count: int
    current_step: ProcessStep
    current_eqp_id: str
    current_state: LotState
    since: datetime
    seconds_in_current_state: float
    is_stuck: bool


class EventResponse(BaseModel):
    """Response shape for a single recorded event (read-back confirmation)."""
    event_id: int
    lot_id: str
    step_id: ProcessStep
    eqp_id: str
    state: LotState
    hold_reason: HoldReason | None
    timestamp: datetime


class DurationBreakdown(BaseModel):
    """
    Generic key -> duration-in-seconds breakdown, used for the
    time_by_step / time_by_equipment / time_by_state endpoints.
    We report seconds (a plain float) rather than a Python timedelta
    object, since timedelta has no native JSON representation -
    this is a common boundary translation at the API layer.
    """
    breakdown: dict[str, float]
