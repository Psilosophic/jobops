from app.pipeline.ats_detect import detect_ats


def test_greenhouse_board_url():
    m = detect_ats("https://boards.greenhouse.io/exampleco/jobs/4011001")
    assert m and m.ats_slug == "greenhouse" and m.token == "exampleco"


def test_lever_url():
    m = detect_ats("https://jobs.lever.co/ExampleCo/a1b2c3d4-1111")
    assert m and m.ats_slug == "lever" and m.token == "exampleco"


def test_ashby_url():
    m = detect_ats("https://jobs.ashbyhq.com/example.co/uuid-here")
    assert m and m.ats_slug == "ashby" and m.token == "example.co"


def test_smartrecruiters_url():
    m = detect_ats("https://jobs.smartrecruiters.com/ExampleCo/744000-iam-engineer")
    assert m and m.ats_slug == "smartrecruiters" and m.token == "exampleco"


def test_workday_detected_but_stays_restricted():
    m = detect_ats("https://exampleco.wd5.myworkdayjobs.com/en-US/careers/job/x")
    assert m and m.ats_slug == "workday" and m.token == "exampleco"


def test_indeed_redirect_unwrapped():
    wrapped = ("https://www.indeed.com/rc/clk?jk=abc&u="
               "https%3A%2F%2Fboards.greenhouse.io%2Fexampleco%2Fjobs%2F123")
    m = detect_ats(wrapped)
    assert m and m.ats_slug == "greenhouse" and m.token == "exampleco"


def test_plain_company_site_no_match():
    assert detect_ats("https://www.exampleco.com/careers") is None
    assert detect_ats("") is None
