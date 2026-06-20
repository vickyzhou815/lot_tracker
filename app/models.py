"""
Domain models for the Lot Tracking service.

These are plain dataclasses - they describe the SHAPE of our data,
similar to a C++ struct. They don't know about the database or the API;
that separation keeps the domain logic testable on its own.

Domain note: a "lot" is a batch of wafers (typically 25 wafers in a
FOUP carrier) that moves through a sequence of process STEPS. At each
step the lot runs on some piece of EQUIPMENT - but step and equipment
are independent dimensions, not a fixed pair:
  - the same step (e.g. ETCH) can run on more than one tool
  - the same tool can sometimes service more than one step
On top of (step, equipment), the lot also has a STATE describing what
it's currently doing there: waiting, actively processing, on hold
(with a reason), or - terminally - scrapped or completed.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class ProcessStep(str, Enum):
    """
    Which process step a lot is routed to.

    C++ comparison: like `enum class ProcessStep : int`, but
    inheriting from `str` means each member IS a string at runtime
    (ProcessStep.ETCH == "ETCH" is True) - convenient for JSON
    serialization later, FastAPI will output "ETCH" directly
    instead of an integer code.

    Real fabs have many more steps; simplified here for the project.
    """
    LITHOGRAPHY = "LITHOGRAPHY"
    ETCH = "ETCH"
    DEPOSITION = "DEPOSITION"
    INSPECTION = "INSPECTION"


class LotState(str, Enum):
    """
    What the lot is currently doing at its (step, equipment) position.

    WAITING and HOLD are similar in that the lot isn't being actively
    processed, but they're semantically different: WAITING is normal
    queue time before processing starts; HOLD is an exception state
    with a reason code, raised either before or during processing.

    SCRAPPED and COMPLETED are terminal - once a lot reaches either,
    we don't expect further transitions.
    """
    WAITING = "WAITING"
    PROCESSING = "PROCESSING"
    HOLD = "HOLD"
    SCRAPPED = "SCRAPPED"
    COMPLETED = "COMPLETED"


TERMINAL_STATES = {LotState.SCRAPPED, LotState.COMPLETED}


class HoldReason(str, Enum):
    """Reason codes recorded when a lot enters HOLD."""
    EQUIPMENT_DOWN = "EQUIPMENT_DOWN"
    QUALITY_REVIEW = "QUALITY_REVIEW"
    RECIPE_MISMATCH = "RECIPE_MISMATCH"
    MANUAL_HOLD = "MANUAL_HOLD"
    UNKNOWN = "UNKNOWN"


@dataclass
class Lot:
    """
    A single wafer lot moving through the fab.

    C++ comparison:
        struct Lot {
            std::string lot_id;
            int wafer_count;
            ProcessStep current_step;
            std::string current_eqp_id;
            LotState current_state;
        };
    The @dataclass decorator auto-generates __init__, __repr__, and
    __eq__ for us - in C++ you'd write the constructor and operator==
    by hand (or default them with `= default;` in C++20).
    """
    lot_id: str
    wafer_count: int
    current_step: ProcessStep
    current_eqp_id: str
    current_state: LotState = LotState.WAITING


@dataclass
class LotEvent:
    """
    A single change in a lot's (step, equipment, state) position.
    This is our audit log - every move creates one of these, and we
    never edit or delete them (append-only) - same philosophy as a
    transaction log in MES: you don't rewrite history, you add to it.

    Not every event changes all three fields at once:
      - moving to a new step usually also assigns new equipment
      - a WAITING -> PROCESSING transition keeps step and equipment
        the same, only the state changes
      - a HOLD event keeps step and equipment the same too, and adds
        a hold_reason
    We record step_id and eqp_id on every event (not just on change)
    so each row is a complete snapshot - this makes querying "where
    was this lot at time T" a single lookup instead of a backward walk
    merging partial updates.
    """
    lot_id: str
    step_id: ProcessStep
    eqp_id: str
    state: LotState
    timestamp: datetime
    hold_reason: HoldReason | None = None
    event_id: int | None = None  # set by the DB on insert, like an AUTO_INCREMENT PK


@dataclass
class LotStatus:
    """
    A computed "current snapshot" view - not stored directly, but
    built from a Lot plus its most recent LotEvent. This is the kind
    of lightweight read-model you'll see a lot in backend work: don't
    store derived data, compute it from the source of truth.
    """
    lot_id: str
    wafer_count: int
    current_step: ProcessStep
    current_eqp_id: str
    current_state: LotState
    since: datetime
    seconds_in_current_state: float = field(default=0.0)
