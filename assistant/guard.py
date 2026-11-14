"""Privacy guard: the assistant never reads, sends, stores or runs anything that touches passwords,
banking details, keys or other credentials. Enforced in code (not just in the prompt), for every brain."""
import os
import re
from pathlib import Path

REFUSAL = "Blocked: this touches passwords, banking or other credentials, which I never access."

# Directories (matched anywhere in the path) that hold credentials, browser data or private mail/messages.
BLOCKED_DIRS = [
    ".ssh", ".gnupg", ".aws", ".azure", ".kube", ".docker", ".password-store", ".config/gcloud", ".config/gh",
    "Library/Keychains", "Library/Cookies", "Library/Safari", "Library/Mail", "Library/Messages",
    "Library/Application Support/Google/Chrome", "Library/Application Support/Firefox",
    "Library/Application Support/BraveSoftware", "Library/Application Support/Microsoft Edge",
    "Library/Application Support/1Password", "Library/Application Support/Bitwarden",
    "Library/Application Support/com.apple.sharedfilelist", "Library/Group Containers/group.com.apple.notes",
    "Keychains",
]

# File names that look like secrets or financial documents.
SENSITIVE_NAME = re.compile(
    r"(passw(or)?d|passwd|credential|secret|token|api[-_ ]?key|private[-_ ]?key|id_(rsa|ed25519|ecdsa|dsa)|"
    r"seed[-_ ]?phrase|recovery[-_ ]?(key|phrase)|wallet|keystore|cvv|\bpin\b|netbanking|net[-_ ]banking|"
    r"bank|statement|credit[-_ ]?card|debit[-_ ]?card|\bupi\b|tax[-_ ]?return|"
    r"^\.env($|\.)|^\.netrc$|^\.git-credentials$|^\.npmrc$|^\.pypirc$|login ?data|^cookies|"
    r"\.(pem|key|p12|pfx|kdbx|keychain(-db)?|1pux|ovpn|jks|gpg|asc)$)", re.I)


def check_path(p: Path) -> Path:
    """Resolve a path and refuse credential locations. Raises PermissionError."""
    p = p.expanduser().resolve()
    s = str(p) + "/"
    for d in BLOCKED_DIRS:
        if f"/{d}/" in s:
            raise PermissionError(REFUSAL + f" ({d})")
    if SENSITIVE_NAME.search(p.name):
        raise PermissionError(REFUSAL + f" ({p.name})")
    return p


def is_sensitive_name(name: str) -> bool:
    return bool(SENSITIVE_NAME.search(name))


# ---- secrets inside text
_SECRET_PATTERNS = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\b(sk-ant-|sk-|gsk_|ghp_|gho_|xox[bap]-|AIza|AKIA|ASIA)[A-Za-z0-9_\-]{12,}"),
    re.compile(r"\b(passw(or)?d|passwd|pwd|passcode|pin|cvv|cvc|otp|secret|api[-_ ]?key|token)\b\s*(is|was|=|:)\s*\S+", re.I),
    re.compile(r"\b(?:\d[ -]?){13,19}\b"),   # card-like numbers (checked with Luhn below)
]


def _luhn(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d = d * 2 - 9 if d * 2 > 9 else d * 2
        total += d
        alt = not alt
    return total % 10 == 0


def _find_secret(text: str):
    for i, pat in enumerate(_SECRET_PATTERNS):
        for m in pat.finditer(text):
            if i == 3:
                digits = re.sub(r"\D", "", m.group())
                if not (13 <= len(digits) <= 19 and _luhn(digits)):
                    continue
            return m
    return None


def contains_secret(text: str) -> bool:
    return _find_secret(text) is not None


def redact(text: str) -> str:
    """Mask secrets in anything returned to the model, so a leaked credential never reaches it."""
    for i, pat in enumerate(_SECRET_PATTERNS):
        def sub(m, i=i):
            if i == 3:
                digits = re.sub(r"\D", "", m.group())
                if not (13 <= len(digits) <= 19 and _luhn(digits)):
                    return m.group()
            if i == 2:  # keep the label, hide the value
                return re.split(r"\s*(?:is|was|=|:)\s*", m.group(), 1, flags=re.I)[0] + ": [hidden]"
            return "[hidden]"
        text = pat.sub(sub, text)
    return text


def args_contain_secret(args: dict) -> bool:
    return any(isinstance(v, str) and contains_secret(v) for v in args.values())


# ---- code the assistant is asked to run
_CODE_BLOCK = re.compile(
    r"(security\s+(find|dump|export|add)-|find-(generic|internet)-password|keychain|\.ssh|\.gnupg|\.aws|\.netrc|"
    r"git-credentials|\.env\b|login\s?data|/Cookies|Library/(Mail|Messages|Safari|Cookies)|"
    r"Application Support/(Google|Firefox|BraveSoftware|Microsoft Edge|1Password|Bitwarden)|"
    r"id_rsa|id_ed25519|\.kdbx|osascript.*(keystroke|password)|pbpaste|sqlite3?.*(logins|cookies)|"
    r"os\.environ|getenv|printenv|\benv\b\s*($|\||;)|ANTHROPIC_API_KEY|GROQ_API_KEY)", re.I)


def check_code(code: str):
    m = _CODE_BLOCK.search(code)
    if m:
        raise PermissionError(REFUSAL + f" (code mentions '{m.group().strip()[:30]}')")


def safe_env() -> dict:
    """Environment for code the assistant runs: API keys and secrets removed."""
    bad = re.compile(r"(key|token|secret|pass|credential|auth)", re.I)
    return {k: v for k, v in os.environ.items() if not bad.search(k)}
