"""Email copy. Edit the wording here; nothing in these templates invents prices or claims.

Placeholders: {business_name} {city} {category} {company_name} {sender_name} {postal_address} {from_email}
"""

from __future__ import annotations

PITCH_SUBJECT = "A website for {business_name}?"

PITCH_BODY = """Hi there,

I came across {business_name} in {city} and noticed you don't have a website yet. When people search for a {category} nearby, a website is often where they look up hours, your location, and how to reach you. Without one, some of them go to a competitor instead.

We're {company_name}. We build clean, mobile-friendly websites for local businesses, and we can take care of the upkeep, social media, and online reviews too, so you don't have to.

Would you be open to a short call or a reply to this email? I'm happy to send a few examples and talk through options.

{sender_name}
{company_name}
{postal_address}

If you'd rather not receive emails like this, just reply with "unsubscribe" and I'll remove you right away.
"""

FOLLOWUP_SUBJECT = "Re: A website for {business_name}?"

FOLLOWUP_BODY = """Hi there,

Following up on my note from last week about a website for {business_name}. Happy to answer any questions, or send over a couple of examples if that would be useful.

Thanks for your time,
{sender_name}
{company_name}
{postal_address}

Reply "unsubscribe" at any time and I won't contact you again.
"""


def render(template: str, **fields: str) -> str:
    """Fill placeholders. Missing keys raise KeyError so a half-filled email is never sent."""
    return template.format(**fields)
