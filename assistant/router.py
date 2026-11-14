"""Fast path: simple, unambiguous commands run directly with no model call (instant, free, works offline).
Anything that doesn't match returns None and goes to the full agent."""
import re
from typing import Optional

from . import tools

_APP = re.compile(r"^\W*(?:please\s+)?(?:open|launch|start)\s+(?!(?:a|an|the|my)\s+(?:file|folder|email|note)\b)([\w .+&-]{2,40}?)\W*$", re.I)
_FILE = re.compile(r"^\W*(?:please\s+)?(?:open|show|pull up)\s+(?:me\s+)?(?:the\s+|my\s+)?(?:file\s+)?([\w .'&-]{2,60}?)\s+(?:file\s+)?(?:(?:in|on|from)\s+(?:my\s+|the\s+)?(downloads|desktop|documents)(?:\s+folder)?)\W*$", re.I)
_VOL = re.compile(r"^\W*(?:set\s+)?(?:the\s+)?volume\s+(?:to\s+)?(\d{1,3})\W*(?:percent|%)?\W*$", re.I)
_TIME = re.compile(r"^\W*what(?:'s| is)?\s+the\s+(?:time|date)\W*$|^\W*what\s+time\s+is\s+it\W*$", re.I)
_LIST = re.compile(r"^\W*(?:what(?:'s| is)\s+on\s+my\s+(?:list|to-?do\s*list)|(?:show|read)\s+(?:me\s+)?my\s+(?:to-?dos?|list))\W*$", re.I)
_BRIEF = re.compile(r"^\W*(?:(?:give\s+me\s+)?(?:my\s+)?(?:briefing|brief\s+me)|what(?:'s| is)\s+(?:up|new)(?:\s+today)?)\W*$", re.I)
_WINDOWS = re.compile(r"^\W*(?:what(?:'s| is| are)?\s+(?:windows|apps|programs)?\s*(?:are\s+)?(?:open|running)(?:\s+(?:now|right now|on my (?:mac|screen)))?|(?:check|show|list)\s+(?:me\s+)?(?:my\s+)?(?:open\s+)?(?:windows|apps)|what(?:'s| is)\s+on\s+my\s+screen)\W*$", re.I)
_ACTIVE = re.compile(r"^\W*(?:what(?:'s| is)\s+(?:the\s+)?(?:active|current|front)\s+(?:window|app)|which\s+(?:window|app)\s+(?:am i|is)\s+(?:in|using|active|open|on|front).*|what\s+am\s+i\s+(?:using|looking at|working on))\W*$", re.I)
_MAIL_CHECK = re.compile(r"^\W*(?:(?:can you\s+)?(?:check|read|show)\s+(?:me\s+)?(?:my\s+)?(?:new\s+|unread\s+)?(?:mail|emails?|inbox)|(?:do i have|are there)\s+(?:any\s+)?(?:new\s+)?(?:mail|emails?)|any\s+(?:new\s+)?(?:mail|emails?))\W*$", re.I)
_MAIL_OPEN = re.compile(r"^\W*(?:can you\s+)?(?:go to|open|launch)\s+(?:the\s+|my\s+)?(?:mail|email|inbox)(?:\s+app)?\W*$", re.I)
_DONE = re.compile(r"^\W*mark\s+(?:to-?do\s+)?#?(\d+)\s+(?:as\s+)?done\W*$", re.I)


def route(text: str) -> Optional[str]:
    try:
        if m := _VOL.match(text):
            return tools.set_volume(int(m.group(1)))
        if _TIME.match(text):
            return tools.get_time()
        if _LIST.match(text):
            return tools.list_todos()
        if _BRIEF.match(text):
            return tools.get_briefing_text()
        if _MAIL_OPEN.match(text):
            return tools.open_app("Mail")
        if _MAIL_CHECK.match(text):
            return tools.check_mail()
        if _ACTIVE.match(text):
            return tools.active_window()
        if _WINDOWS.match(text):
            return tools.list_windows()
        if m := _DONE.match(text):
            return tools.complete_todo(int(m.group(1)))
        if m := _FILE.match(text):
            return tools.open_file(m.group(1).strip(), m.group(2))
        if m := _APP.match(text):
            return tools.open_app(m.group(1).strip())
    except Exception as e:
        return f"That didn't work: {e}"
    return None
