# Lot Tracking Service (MES Portfolio Project)

A small backend service for tracking wafer lots moving through a
semiconductor fab, inspired by real MES (Manufacturing Execution
System) concepts from 300mm wafer fab operations.

## Domain model

A **lot** (a batch of wafers) moves through a sequence of **process
steps** (e.g. lithography, etch, deposition, inspection). At each
step it runs on a piece of **equipment**.
Separately from step/equipment, a lot has a **state**: `WAITING`,
`PROCESSING`, `HOLD` (with a reason code), or - terminally -
`SCRAPPED` / `COMPLETED`.

Every change to a lot's (step, equipment, state) is recorded as an
append-only event, the same way a real MES keeps a transaction log
rather than overwriting history.

## Status

🚧 In progress. Currently implemented:

- [x] Domain models (`app/models.py`)
- [x] Rule engine: per-step / per-equipment / per-state time
      breakdowns, hold-reason counts, stuck-lot detection
      (`app/rules.py`)
- [ ] REST API (FastAPI)
- [ ] MySQL persistence
- [ ] Containerization (Docker / docker-compose)
- [ ] Metrics + dashboard (Prometheus / Grafana)
- [ ] Deployment (AWS EC2)

## Why this project

Built as a hands-on portfolio piece to demonstrate backend service
design (REST API, relational schema, containerization, observability,
cloud deployment) applied to a domain I have real production
experience in - MES / wafer fab operations - rather than a generic
tutorial app.


