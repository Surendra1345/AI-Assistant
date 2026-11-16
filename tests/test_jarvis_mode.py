import pytest

from assistant import brain, config, main
from assistant.voice import Voice


@pytest.mark.parametrize("phrase", ["thanks", "Thank you Jarvis", "that's all", "that will be all", "okay thanks", "go to sleep",
                                    "Thanks so much", "nothing else", "that's it"])
def test_dismiss_phrases_close_the_conversation(phrase):
    assert main.DISMISS.match(phrase)
    assert main.handle(None, None, phrase) in ("Anytime.", "Of course.", "At your service.", "Standing by.")


@pytest.mark.parametrize("phrase", ["thanks for the update, now open Safari", "what's the time", "no thanks send it"])
def test_ordinary_requests_are_not_dismissals(phrase):
    assert not main.DISMISS.match(phrase)


def test_conversation_window_is_open_by_default(monkeypatch):
    v = Voice()
    monkeypatch.setattr(config, "FOLLOWUP_SECONDS", -1)
    monkeypatch.setattr(v, "using_speakers", lambda: True)
    assert v.followup_seconds() == 20
    monkeypatch.setattr(v, "using_speakers", lambda: False)
    assert v.followup_seconds() == 30
    monkeypatch.setattr(config, "FOLLOWUP_SECONDS", 0)
    assert v.followup_seconds() == 0         # user can switch it off


def test_persona_and_title(monkeypatch):
    monkeypatch.setattr(config, "USER_TITLE", "sir")
    p = brain._system_prompt()
    assert "You are Jarvis" in p and 'Address the user as "sir"' in p and "{name}" not in p and "{title_rule}" not in p
    monkeypatch.setattr(config, "USER_TITLE", "")
    assert "Use the user's name only occasionally" in brain._system_prompt()


def test_spoken_ack_comes_before_the_slow_tool_runs(monkeypatch):
    events = []
    spoken = []

    class Voice_:
        def speak(self, text, barge=True, settle=True):
            events.append("speak"); spoken.append((text, barge, settle))
    monkeypatch.setattr(brain.tools, "execute_tool", lambda n, a, t=None: events.append("tool") or "ok")
    monkeypatch.setattr(config, "ACK_SPOKEN", True)
    a = brain.Agent(None)
    a.on_first_tool = main.make_ack(Voice_())
    a._announce("news_search"); a._announce("fetch_page")     # only the first tool of a turn is announced
    assert spoken == [("Checking the latest news.", False, False)]
    a._announce("calculate")
    assert len(spoken) == 1
    a.run  # (a new turn resets the flag)
    a._announced = False; a._announce("calculate")
    assert len(spoken) == 1                                   # quick tools stay silent


def test_ack_can_be_turned_off(monkeypatch):
    monkeypatch.setattr(config, "ACK_SPOKEN", False)
    said = []
    ack = main.make_ack(type("V", (), {"speak": lambda self, *a, **k: said.append(a)})())
    ack("web_search")
    assert said == []
