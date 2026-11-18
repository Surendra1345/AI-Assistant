import pytest

from assistant import brain, config, tools
from tests.test_features import call, groq_agent, msg

_SCAN = ("Gmail | 101 | 0 | Naukri <jobs@naukri.com> | Your application to Infosys was sent\n"
         "Gmail | 102 | 2 | Myntra <updates@myntra.com> | Add colour to your cart 🛒\n"
         "Gmail | 103 | 4 | TCS Careers <careers@tcs.com> | Thank you for applying: Data Engineer\n"
         "Gmail | 104 | 6 | HDFC Bank <alerts@hdfcbank.net> | Your account statement\n"
         "Gmail | 105 | 9 | LinkedIn <jobs-noreply@linkedin.com> | You applied for ML Engineer at Wipro\n"
         "Gmail | 106 | 14 | Accenture <recruit@accenture.com> | Interview invitation\n")


@pytest.fixture
def inbox(monkeypatch):
    monkeypatch.setattr(tools.macos, "osascript", lambda *a, **k: _SCAN)


def test_search_mail_finds_applications_in_the_period(inbox):
    out = tools.search_mail("applied, application, applying, interview, career", days=10)
    assert "3 match" in out
    assert "#1 (today) Naukri (Gmail): Your application to Infosys" in out
    assert "#2 (4 days ago) TCS Careers" in out and "#3 (9 days ago) LinkedIn" in out
    assert "Accenture" not in out            # 14 days old: outside the 10 days
    assert "Myntra" not in out and "@" not in out


def test_search_mail_hides_private_and_reports_empty(inbox):
    out = tools.search_mail("statement, hdfc", days=10)
    assert "HDFC" not in out and "private ones" in out
    assert "None match" in tools.search_mail("zzzz", days=10)
    assert "5 match" not in tools.search_mail("", days=3) and "#2 (2 days ago) Myntra (Gmail)" in tools.search_mail("", days=3)


def test_matches_sender_domain_too(inbox):
    assert "TCS Careers" in tools.search_mail("careers@", days=10)


@pytest.mark.parametrize("text,single", [
    ("open Spotify", True), ("set a reminder to call mom at six", True),
    ("check my mail from past 10 days which company that I have applied", False),
    ("open my resume and email it to me", False), ("remember my name then tell me the time", False),
    ("make notes of the companies", False),
])
def test_only_short_single_requests_stop_after_one_tool(text, single):
    assert brain._single_step(text) is single


def test_mail_lookup_no_longer_ends_the_request(monkeypatch, inbox):
    """The bug from the user's log: check_mail ran, its list was spoken, and the real request was dropped."""
    monkeypatch.setattr(tools, "check_mail", lambda count=5: "204 unread.\n#1 [unread] Google: Security alert")
    a = groq_agent(monkeypatch, [
        msg(calls=[call("check_mail", {})]),
        msg(calls=[call("search_mail", {"keywords": "applied, application, applying", "days": 10})]),
        msg(calls=[call("save_note", {"title": "Job applications", "content": "Infosys (today), TCS, Wipro"})]),
        msg("You applied to Infosys, TCS and Wipro in the last ten days. I saved the list as a note."),
    ])
    out = a.run("check my mail from past 10 days which company that I have applied so make notes")
    assert out.startswith("You applied to Infosys") and len(a.payloads) == 4
    assert {"check_mail", "search_mail", "save_note"} <= a.turn_tools
    sent = {t["function"]["name"] for t in a.payloads[0][1]["tools"]}
    assert {"search_mail", "read_email", "save_note"} <= sent          # Groq is offered the tools this needs


def test_you_can_speak_for_longer(monkeypatch):
    assert config.MAX_REQUEST_SECONDS >= 30 and config.PAUSE_SECONDS >= 1.0
