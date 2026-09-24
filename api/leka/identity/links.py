"""The links in authentication emails, built in one place.

They point at the FRONTEND — the pages a person opens — never at the API
routes those pages call. Until LEKA-330's fix they did the opposite: a
relative "/auth/verify/<token>", no domain, an API path without its /api/v1.
Unclickable in a mail client and a 404 when typed. tests/test_auth_emails.py
now checks each link against the page files in web/app.

    verification  web/app/(auth)/verify/[token]/page.tsx   → /verify/<token>
    reset         web/app/(auth)/reset-password/page.tsx   → /reset-password?token=<token>

"(auth)" is a Next.js route group: it organises files and never appears in
the URL.
"""

from __future__ import annotations

from urllib.parse import quote, urlencode

from leka.core.config import settings


def verification_link(token: str) -> str:
    return f"{settings.web_url}/verify/{quote(token, safe='')}"


def reset_link(token: str) -> str:
    return f"{settings.web_url}/reset-password?{urlencode({'token': token})}"
