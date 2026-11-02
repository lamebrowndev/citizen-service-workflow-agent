# Citizen Service Workflow Agent

A deterministic domain backend and Model Context Protocol (MCP) server for **Civitas**, a fictional
city. The service models everyday municipal workflows — identity verification, parking permits,
birth certificate copies, bulk waste pickups, address changes, street issue reports, office
appointments, and human escalation — on top of a seeded SQLite database. Every tool is
idempotent by design: the same calls against the same seeded database produce the same results
and the same database contents. No language-model or agent code lives in this phase; later
phases build an agent, evaluation harness, and web service on top of these tools.

**Status: Phase 1 — domain backend + MCP server**

> **Disclaimer:** Civitas is a fictional city. All names, addresses, vehicles, and records in this
> repository are synthetic. This project is not affiliated with any government or public agency.

## Quickstart

Requirements: Python 3.13 and [uv](https://docs.astral.sh/uv/). Docker is not required.

```bash
make setup    # create .venv and install runtime + dev dependencies
make seed     # create var/citizen.db from the bundled fixture (--force)
make test     # run the full test suite
make mcp      # start the MCP server on stdio
```

Configuration is read from the environment (see `.env.example`):

| Variable | Default | Meaning |
| --- | --- | --- |
| `CSA_DB_PATH` | `var/citizen.db` | SQLite database path, resolved to an absolute path |
| `CSA_TOKEN_SECRET` | `civitas-dev-secret` | HMAC secret for citizen tokens; a warning is logged when the default is used |
| `CSA_LOG_LEVEL` | `INFO` | Log level for stderr logging |

The seed CLI also accepts a custom fixture:

```bash
uv run csa-seed --db var/citizen.db --fixture path/to/fixture.json --force
```

## Tools

All 17 tools are exposed with identical names and arguments in `CitizenServices` and over MCP.

| Tool | Read/Write | Purpose |
| --- | --- | --- |
| `verify_citizen` | Read | Verify name, date of birth, and postal code; return a signed citizen token |
| `get_citizen_profile` | Read | Return profile, vehicles, applications, booked appointments, and scheduled pickups |
| `update_address` | Write | Change the citizen's street address and postal code |
| `get_service_info` | Read | Return a service's description, requirements, fee rules, and processing days |
| `check_eligibility` | Read | Return whether a citizen is eligible and every applicable reason code |
| `quote_fee` | Write | Create or replay a fee quote for a paid service |
| `pay_quote` | Write | Simulate charging the card on file for a quote and record the payment |
| `apply_parking_permit` | Write | Submit a parking permit application against a paid quote |
| `request_birth_certificate` | Write | Request 1–5 certified birth certificate copies against a paid quote |
| `list_pickup_dates` | Read | List the next four bulk-waste pickup dates for the citizen's zone |
| `schedule_bulk_pickup` | Write | Schedule one bulk-waste pickup on an offered date |
| `report_street_issue` | Write | Report a pothole, streetlight, graffiti, or missed collection |
| `get_case_status` | Read | Look up an application or public street issue by case ID |
| `list_appointment_slots` | Read | List free 30-minute appointment slots at an office on a date |
| `book_appointment` | Write | Book a free office appointment slot |
| `cancel_appointment` | Write | Cancel a booked appointment and free its slot |
| `escalate_to_human` | Write | Create a human-handoff escalation, optionally tied to a citizen |

## Connect an MCP client

The bundled inspector is the quickest way to explore the tools:

```bash
make seed
make inspector
```

To register the server with Claude Code:

```bash
claude mcp add civitas -- uv --directory <repo-path> run csa-mcp
```

The server uses stdio by default. For streamable HTTP:

```bash
make mcp-http            # uv run csa-mcp --transport streamable-http
```

## Design notes

- **Signed citizen tokens.** `verify_citizen` returns `CTK.<citizen_id>.<signature>`, where the
  signature is an HMAC-SHA256 prefix over the citizen ID. Token verification is constant-time and
  never relies on unauthenticated lookups. Only verification returns a token; there is no way to
  enumerate identities from an ID.
- **Deterministic, idempotent IDs.** Record IDs are hashes of normalized key content, so retrying
  the same request addresses the same row. Replays return the stored result with `created=false`
  (or `changed=false`) and do not write again. Inserts never overwrite an existing primary key.
  Replays match only live records (open quotes, scheduled pickups, booked appointments), so retries
  are safe and repeat orders create new records.
- **Simulated clock.** Domain code never reads the wall clock. "Today" is the `meta.today` value
  in the database (2026-03-02 in the bundled fixture), which makes quotes, applications, pickups,
  issues, and escalations reproducible.
- **Structured error codes.** Domain failures raise `DomainError` with a stable code
  (`INVALID_TOKEN`, `NOT_ELIGIBLE`, `SLOT_UNAVAILABLE`, and so on) and a short message that never
  contains another citizen's data. Over MCP these become `isError=true` results whose text begins
  with the code.
- **Single-transaction writes.** Each service call opens its own SQLite connection and runs one
  transaction (`BEGIN IMMEDIATE` for writes). A domain error rolls back, leaving the database
  unchanged.

## Development

```bash
make fmt         # format
make lint        # ruff
make typecheck   # mypy --strict
make check       # format check + lint + typecheck + tests
```

The project targets Python 3.13 and uses only `mcp` and `pydantic` at runtime, with `pytest`,
`pytest-asyncio`, `ruff`, and `mypy` for development.

## License

MIT. See [LICENSE](LICENSE).
