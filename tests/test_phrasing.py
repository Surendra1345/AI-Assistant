import re

import pytest

from assistant import config, phrasing as ph


@pytest.fixture(autouse=True)
def _title(monkeypatch):
    monkeypatch.setattr(config, "USER_TITLE", "")


@pytest.mark.parametrize("tool,raw,must", [
    ("open_app", "Opened Spotify.", "Spotify"), ("quit_app", "Closed Spotify.", "Spotify"),
    ("set_volume", "Volume set to 30.", "30 percent"), ("music_control", "Playing in Spotify.", ""),
    ("music_control", "Song X by Artist Y (playing)", "Song X by Artist Y"),
    ("open_file", "Opened resume.pdf (2 other matches).", "2 other matches"),
    ("calculate", "15% of 2400 = 360", "360"), ("remember", "Remembered.", ""),
])
def test_results_become_sentences_not_log_lines(tool, raw, must):
    for _ in range(12):                      # every random variant
        out = ph.humanize(tool, raw)
        assert must in out and out != raw
        assert not out.startswith(("Opened ", "Closed ", "Volume set", "Remembered."))


def test_time_is_spoken_like_a_person():
    out = ph.humanize("get_time", "Monday 16 November 2026, 10:32")
    assert re.search(r"\d{1,2}:\d{2}", out) and "2026" not in out


def test_todos_become_a_spoken_list():
    out = ph.humanize("list_todos", "#1 call bank — due 2026-11-16T09:00\n#2 buy milk")
    assert out.startswith("You have 2 things on your list: call bank") and "buy milk" in out and "#" not in out and "—" not in out
    assert "clear" in ph.humanize("list_todos", "Nothing on the list.")


def test_add_todo_with_time_and_repeat():
    out = ph.humanize("add_todo", "Added #3: water plants (due 2026-11-17T09:00, repeats daily)")
    assert "water plants" in out and "9:00 AM" in out and "daily" in out and "#" not in out


def test_mail_summary_is_spoken():
    raw = ("204 unread.\n#1 [unread] Google <no-reply@accounts.google.com>: Security alert\n"
           "#2 [unread] Binance: Your Ramadan Trading Journey Starts Here 👉🚀\n#3 Myntra: Sale")
    out = ph.humanize("check_mail", raw)
    assert out.startswith("You have 204 unread emails. The latest are from Google, Security alert; then Binance")
    assert "#" not in out and "@" not in out and "🚀" not in out and "[" not in out


def test_title_is_used_when_configured(monkeypatch):
    monkeypatch.setattr(config, "USER_TITLE", "sir")
    assert any("sir" in ph.humanize("get_time", "x") for _ in range(60))


@pytest.mark.parametrize("raw", ["ERROR: boom", "Blocked: credentials", "I couldn't find a file matching 'x'.", "That didn't work: no app",
                                 "Something unrecognised"])
def test_errors_and_unknowns_pass_through_unchanged(raw):
    assert ph.humanize("open_app", raw) == raw
