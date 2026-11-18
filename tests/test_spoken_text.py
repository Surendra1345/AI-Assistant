import pytest

from assistant import tools
from assistant.voice import Voice


def test_mail_list_is_spoken_naturally():
    raw = ("204 unread.\n#1 [unread] Google <no-reply@accounts.google.com>: Security alert\n"
           "#2 [unread] Binance <do_not_reply@mailersp2.binance.com>: Your Ramadan Trading Journey Starts Here  👉🚀🌙\n"
           "#3 Myntra: Add A Li'l Colour To Your Cart 🛒 🎨 https://x.example/y")
    said = Voice.tts_clean(raw)
    assert "@" not in said and "<" not in said and "[" not in said and "#" not in said and "http" not in said
    assert "🚀" not in said and "🛒" not in said
    assert "Number 1, unread: Google: Security alert" in said and "Number 3 Myntra" in said


def test_check_mail_drops_addresses_and_emoji(monkeypatch):
    monkeypatch.setattr(tools.macos, "osascript", lambda *a, **k:
                        "UNREAD:2\nGmail | 1 | false | Binance <do_not_reply@mailersp2.binance.com> | Join us 🚀🌙 today | 10\n"
                        "Gmail | 2 | true | Myntra <updates@myntra.com> | Sale 🛒 | 20\n")
    out = tools.check_mail()
    assert "@" not in out and "<" not in out and "🚀" not in out
    assert "#1 [unread] Binance (Gmail): Join us today" in out and "#2 Myntra (Gmail): Sale" in out


@pytest.mark.parametrize("remark", ["Oh, my God.", "Oh, it's waiting on.", "Hmm, let me think", "Wow that's loud"])
def test_stray_remarks_are_not_taken_as_requests(remark):
    v = Voice(); v.last_conf = -0.2
    assert not v._plausible_followup(remark)


@pytest.mark.parametrize("request_", ["How are you?", "Oh and also check my mail please", "open WhatsApp", "what's the time"])
def test_real_requests_still_pass(request_):
    v = Voice(); v.last_conf = -0.2
    assert v._plausible_followup(request_)
