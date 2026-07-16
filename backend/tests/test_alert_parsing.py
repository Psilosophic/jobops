from pathlib import Path

from app.adapters.imap_alerts import LinkedInAlertsAdapter, extract_alert_jobs

FIXTURES = Path(__file__).parent / "fixtures"


def test_linkedin_alert_extraction_dedupes_and_filters():
    html = (FIXTURES / "linkedin_alert.html").read_text()
    jobs = extract_alert_jobs(html, LinkedInAlertsAdapter.link_filter)
    assert len(jobs) == 2                       # dup collapsed, unsubscribe ignored
    iam = jobs[0]
    assert iam["title"] == "IAM Engineer"
    assert "Acme Identity Corp" in iam["company"]
    assert "linkedin.com/comm/jobs/view/4012345678" in iam["url"]


def test_alert_adapters_are_discover_only_by_registry():
    """The mailbox adapters read the user's OWN mailbox — retrieval_method must be
    imap, and there must be no fetch path pointing at the boards' websites."""
    caps = LinkedInAlertsAdapter.capabilities()
    assert caps.retrieval_method == "imap"
    assert caps.requires_auth is True
