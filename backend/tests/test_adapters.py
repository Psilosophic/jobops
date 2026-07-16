"""Adapter contract tests — offline, fixture-driven via respx. If an upstream API
shape changes, these fail loudly instead of silently ingesting garbage."""
import json
from pathlib import Path

import httpx
import pytest
import respx

from app.adapters.base import parse_salary_text
from app.adapters.greenhouse import GreenhouseAdapter
from app.adapters.lever import LeverAdapter

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.asyncio
@respx.mock
async def test_greenhouse_normalization():
    payload = json.loads((FIXTURES / "greenhouse_jobs.json").read_text())
    respx.get("https://boards-api.greenhouse.io/v1/boards/exampleco/jobs").mock(
        return_value=httpx.Response(200, json=payload)
    )
    adapter = GreenhouseAdapter({"boards": ["exampleco"],
                                 "company_names": {"exampleco": "Example Co"}})
    postings = await adapter.fetch()
    assert len(postings) == 2

    iam = postings[0]
    assert iam.external_id == "4011001"
    assert iam.company_name == "Example Co"
    assert iam.is_remote is True
    assert "PingFederate" in iam.description_text
    assert "<p>" not in iam.description_text            # html stripped
    assert iam.salary_min == 115000 and iam.salary_max == 140000
    assert iam.fingerprint() == iam.fingerprint()        # stable

    support = postings[1]
    assert support.is_remote is False
    assert "Denver" in support.location_raw


@pytest.mark.asyncio
@respx.mock
async def test_lever_normalization():
    payload = json.loads((FIXTURES / "lever_postings.json").read_text())
    respx.get("https://api.lever.co/v0/postings/exampleco").mock(
        return_value=httpx.Response(200, json=payload)
    )
    adapter = LeverAdapter({"orgs": ["exampleco"]})
    postings = await adapter.fetch()
    assert len(postings) == 1
    p = postings[0]
    assert p.is_remote is True
    assert p.salary_min == 120000 and p.salary_max == 150000
    assert p.employment_type == "full-time"
    assert p.posted_at is not None


def test_salary_parser_variants():
    assert parse_salary_text("pays $115,000 - $140,000 annually") == (115000, 140000)
    assert parse_salary_text("range: $95k-$120k DOE") == (95000, 120000)
    assert parse_salary_text("$120 - $95") == (95000, 120000)   # swapped + k-inference
    assert parse_salary_text("competitive salary") == (None, None)
    assert parse_salary_text("") == (None, None)


@pytest.mark.asyncio
@respx.mock
async def test_greenhouse_http_error_propagates():
    respx.get("https://boards-api.greenhouse.io/v1/boards/deadco/jobs").mock(
        return_value=httpx.Response(500)
    )
    adapter = GreenhouseAdapter({"boards": ["deadco"]})
    with pytest.raises(httpx.HTTPStatusError):
        await adapter.fetch()
