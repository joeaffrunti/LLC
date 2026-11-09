"""Check that a sending domain has SPF, DKIM, and DMARC records before going live.

Uses `dig` or `nslookup` (whichever is installed), so it works on a normal workstation.
"""

from __future__ import annotations

import re
import shutil
import subprocess

_QUOTED = re.compile(r'"([^"]*)"')


def parse_txt(output: str) -> list[str]:
    """Extract TXT record values from `dig +short` or `nslookup` output."""
    records = []
    for line in output.splitlines():
        if "v=" not in line and "k=" not in line and "p=" not in line:
            continue
        quoted = _QUOTED.findall(line)
        records.append("".join(quoted) if quoted else line.strip())
    return records


def lookup_txt(name: str, resolver_timeout: int = 10) -> list[str] | None:
    """Return TXT values for name, or None if no DNS tool is available."""
    if shutil.which("dig"):
        cmd = ["dig", "+short", "TXT", name]
    elif shutil.which("nslookup"):
        cmd = ["nslookup", "-type=TXT", name]
    else:
        return None
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=resolver_timeout).stdout
    except subprocess.TimeoutExpired:
        return []
    return parse_txt(out)


def check_domain(domain: str, dkim_selector: str = "default", lookup=lookup_txt) -> dict[str, str]:
    """Return a status line per record type: 'ok', 'missing', or 'no DNS tool available'."""
    results = {}

    spf = lookup(domain)
    if spf is None:
        return {"error": "no dig or nslookup found on this machine"}
    spf_hits = [r for r in spf if r.lower().startswith("v=spf1")]
    results["SPF"] = "ok" if spf_hits else "missing (add a TXT record starting with v=spf1)"

    dkim = lookup(f"{dkim_selector}._domainkey.{domain}") or []
    dkim_hits = [r for r in dkim if "v=DKIM1" in r or "p=" in r]
    results["DKIM"] = "ok" if dkim_hits else (
        f"missing for selector '{dkim_selector}' (set up DKIM in your mail provider, then pass its selector)")

    dmarc = lookup(f"_dmarc.{domain}") or []
    dmarc_hits = [r for r in dmarc if r.lower().startswith("v=dmarc1")]
    results["DMARC"] = "ok" if dmarc_hits else "missing (add a TXT record at _dmarc starting with v=DMARC1)"
    return results
