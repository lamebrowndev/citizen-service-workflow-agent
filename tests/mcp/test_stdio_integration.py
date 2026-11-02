"""End-to-end MCP stdio integration against a real subprocess."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import CallToolResult

from citizen_agent.domain.models import Fixture
from citizen_agent.domain.store import Store

EXPECTED_TOOLS = {
    "verify_citizen",
    "get_citizen_profile",
    "update_address",
    "get_service_info",
    "check_eligibility",
    "quote_fee",
    "pay_quote",
    "apply_parking_permit",
    "request_birth_certificate",
    "list_pickup_dates",
    "schedule_bulk_pickup",
    "report_street_issue",
    "get_case_status",
    "list_appointment_slots",
    "book_appointment",
    "cancel_appointment",
    "escalate_to_human",
}


async def _call(session: ClientSession, name: str, arguments: dict[str, object]) -> CallToolResult:
    result = await session.call_tool(name, arguments)
    assert isinstance(result, CallToolResult)
    return result


def _structured(result: CallToolResult) -> dict[str, object]:
    assert result.is_error is False
    assert isinstance(result.structured_content, dict)
    return result.structured_content


async def test_stdio_server_lists_tools_and_runs_parking_flow(
    tmp_path: Path, fixture: Fixture
) -> None:
    db_path = tmp_path / "mcp.db"
    Store.create_from_fixture(db_path, fixture)
    citizen = next(c for c in fixture.citizens if c.citizen_id == "CIT-0001")
    plate = next(v.license_plate for v in fixture.vehicles if v.citizen_id == "CIT-0001")

    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "citizen_agent.mcp_server"],
        env={**os.environ, "CSA_DB_PATH": str(db_path)},
    )

    async with asyncio.timeout(30):
        async with (
            stdio_client(params) as (read_stream, write_stream),
            ClientSession(read_stream, write_stream) as session,
        ):
            await session.initialize()

            tools = (await session.list_tools()).tools
            assert {tool.name for tool in tools} == EXPECTED_TOOLS
            by_name = {tool.name: tool for tool in tools}
            for tool in tools:
                assert tool.description
                assert len(tool.description.split()) <= 80
                assert tool.input_schema
                assert tool.input_schema.get("type") == "object"
                assert tool.output_schema

            read_tools = {
                "verify_citizen",
                "get_citizen_profile",
                "get_service_info",
                "check_eligibility",
                "list_pickup_dates",
                "get_case_status",
                "list_appointment_slots",
            }
            for name, tool in by_name.items():
                annotations = tool.annotations
                assert annotations is not None
                assert annotations.read_only_hint is (name in read_tools)
                if name not in read_tools:
                    assert annotations.idempotent_hint is True
                if name in {"pay_quote", "cancel_appointment"}:
                    assert annotations.destructive_hint is True

            service_enum = by_name["quote_fee"].input_schema["properties"]["service_type"]["enum"]
            assert service_enum == [
                "PARKING_PERMIT",
                "BIRTH_CERTIFICATE_COPY",
                "BULK_WASTE_PICKUP",
                "ADDRESS_CHANGE",
                "STREET_ISSUE_REPORT",
                "OFFICE_APPOINTMENT",
            ]

            verified = await _call(
                session,
                "verify_citizen",
                {
                    "full_name": citizen.full_name,
                    "date_of_birth": citizen.date_of_birth,
                    "postal_code": citizen.postal_code,
                },
            )
            verified_data = _structured(verified)
            assert set(verified_data) == {"citizen_token", "full_name"}
            token = str(verified_data["citizen_token"])

            eligibility = await _call(
                session,
                "check_eligibility",
                {"citizen_token": token, "service_type": "PARKING_PERMIT"},
            )
            assert _structured(eligibility)["eligible"] is True

            quote = await _call(
                session,
                "quote_fee",
                {"citizen_token": token, "service_type": "PARKING_PERMIT"},
            )
            quote_data = _structured(quote)
            assert quote_data["amount_cents"] == 3000
            quote_id = str(quote_data["quote_id"])

            payment = await _call(
                session, "pay_quote", {"citizen_token": token, "quote_id": quote_id}
            )
            payment_data = _structured(payment)
            assert payment_data["status"] == "PAID"
            payment_id = str(payment_data["payment_id"])

            application = await _call(
                session,
                "apply_parking_permit",
                {
                    "citizen_token": token,
                    "license_plate": plate,
                    "payment_id": payment_id,
                },
            )
            application_data = _structured(application)
            assert application_data["status"] == "SUBMITTED"
            application_id = str(application_data["application_id"])

            replay = await _call(
                session,
                "apply_parking_permit",
                {
                    "citizen_token": token,
                    "license_plate": plate,
                    "payment_id": payment_id,
                },
            )
            replay_data = _structured(replay)
            assert replay_data["application_id"] == application_id
            assert replay_data["created"] is False

            failing = await _call(
                session,
                "get_citizen_profile",
                {"citizen_token": "CTK.CIT-0001.BAD"},
            )
            assert failing.is_error is True
            text = "".join(
                block.text for block in failing.content if getattr(block, "type", "") == "text"
            )
            assert "INVALID_TOKEN" in text
