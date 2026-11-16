import json
import time

import pytest

from assistant import brain, router, tools
from assistant.voice import Voice


@pytest.fixture
def mac(monkeypatch):
    calls = []

    def fake(script, *args, **k):
        calls.append((script, args))
        if "name of processes" in script and "return (name of processes)" in script:
            return "Finder, Spotify"
        if "not running" in script:
            return "ok"
        return "Song by Artist (playing)" if "current track" in script else ""
    monkeypatch.setattr(tools.macos, "osascript", fake)
    return calls


@pytest.mark.parametrize("phrase,expect", [("play music", "tell application \"Spotify\" to play"), ("pause", "to pause"),
                                           ("next song", "to next track"), ("skip", "to next track"),
                                           ("previous song", "to previous track"), ("play", "to play")])
def test_voice_music_commands_skip_the_model(mac, phrase, expect):
    assert router.route(phrase)
    assert expect in mac[-1][0]


def test_whats_playing_and_quit(mac):
    assert "Song by Artist" in router.route("what's playing")
    assert router.route("close Spotify") == "Closed Spotify."
    assert mac[-1][1] == ("Spotify",)


def test_quit_of_non_app_or_vague_phrase_falls_through(monkeypatch):
    monkeypatch.setattr(tools.macos, "osascript", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no such app")))
    assert router.route("close the door") is None
    assert router.route("close it") is None
    assert router.route("play Shape of You") is None      # needs the agent (and it can't search songs)


def test_music_app_is_whitelisted(mac):
    tools.music_control("play", app='Spotify" & (do shell script "x") & "')   # injected text must never reach the script
    assert 'do shell script' not in mac[-1][0]


def test_groq_gets_a_small_relevant_tool_list():
    a = brain.Agent(None)
    full = len(json.dumps(brain._openai_tools(a.tool_schemas)))
    names = lambda t: {x["name"] for x in a._tools_for(t)}
    resume = names("can you check my resume")
    assert {"find_files", "read_file", "open_file"} <= resume and "stock_quote" not in resume and "run_code" not in resume
    assert len(json.dumps(brain._openai_tools(a._tools_for("hello")))) < full * 0.5
    assert {"stock_quote", "market_movers"} <= names("which stock is going high")
    assert "stock_quote" in names("and the other one")            # sticky: follow-ups keep last turn's tools
    bg = brain.Agent(None, task_id=1)
    assert bg._tools_for("anything") == bg.tool_schemas             # background tasks get everything


def test_answer_to_a_question_needs_no_wake_word(monkeypatch):
    v = Voice()
    monkeypatch.setattr(v, "using_speakers", lambda: True)
    monkeypatch.setattr(time, "sleep", lambda s: None)
    v.speak("Did you want more details about Eli Lilly?")
    assert v.follow_until > time.time() + 5          # next reply is accepted without "hey jarvis"
    v.speak("Opened Safari.")
    assert v.follow_until == 0.0
    v.speak("Say yes or no?", barge=False)           # approval prompts listen on their own
    assert v.follow_until == 0.0
