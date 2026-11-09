"""Rule-based intent detection for inbound replies.

Deliberately simple and conservative: anything ambiguous becomes "other" and is
routed to a human. Only "unsubscribe" triggers an automatic action.
"""

from __future__ import annotations

import re

INTENTS = ("unsubscribe", "bounce", "out_of_office", "not_interested", "interested", "question", "other")

_UNSUBSCRIBE = re.compile(
    r"\b(unsubscribe|remove me|take me off|stop (emailing|contacting|messaging)|do not contact|don'?t contact|opt[- ]?out)\b",
    re.I,
)
_OOO = re.compile(r"out of (the )?office|automatic reply|auto[- ]?reply|on vacation|away from (my|the) desk", re.I)
_NOT_INTERESTED = re.compile(
    r"not interested|no thanks|no,? thank you|we('re| are) (all )?set|already have (a |an )?(website|site)|"
    r"not (right )?now|no need|not a good time|not looking",
    re.I,
)
_INTERESTED = re.compile(
    r"\b(interested|sounds good|tell me more|send (me )?(more|pricing|details|examples)|how much|"
    r"let'?s talk|call me|would love|sure|yes)\b",
    re.I,
)

_QUOTE_MARKER = re.compile(r"^\s*On .+wrote:\s*$", re.M)


def strip_quoted(text: str) -> str:
    """Remove quoted history ("> ..." lines and everything after an 'On ... wrote:' line)."""
    text = text.replace("\r\n", "\n")
    m = _QUOTE_MARKER.search(text)
    if m:
        text = text[: m.start()]
    lines = [ln for ln in text.split("\n") if not ln.lstrip().startswith(">")]
    return "\n".join(lines).strip()


def classify(reply_body: str) -> str:
    text = strip_quoted(reply_body)
    if not text:
        return "other"
    if _UNSUBSCRIBE.search(text):
        return "unsubscribe"
    if _OOO.search(text):
        return "out_of_office"
    # Check negatives before positives: "not interested" contains "interested".
    if _NOT_INTERESTED.search(text):
        return "not_interested"
    if _INTERESTED.search(text):
        return "interested"
    if "?" in text:
        return "question"
    return "other"
