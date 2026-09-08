"""Refuse requests that did not come through Cloudflare.

Cloud Run has to accept unauthenticated callers for Cloudflare to reach it,
which leaves the service's own *.run.app URL answering anyone who finds it --
Access guards the hostname, not the origin. The Worker attaches a shared secret
that only it knows, so a request without it did not come through the front
door.

Not a substitute for Access: it proves the request was proxied, not who sent
it. Access still decides who is allowed in.
"""
from __future__ import annotations

import hmac
import os

import streamlit as st

HEADER = "X-Butterfly-Key"
EXPECTED = os.environ.get("BUTTERFLY_KEY", "")


def check() -> None:
    """Stop the page unless the proxy secret is present and correct.

    With no BUTTERFLY_KEY set the gate is open, so local runs and any
    deployment that has not configured it behave exactly as before.
    """
    if not EXPECTED:
        return

    try:
        headers = st.context.headers
        # HTTP/2 lowercases header names and proxies are free to re-case them,
        # so match without regard to case rather than trusting one spelling.
        supplied = next(
            (v for k, v in headers.items() if k.lower() == HEADER.lower()), "")
    except Exception:
        # No request context at all -- a bare `streamlit run` from a terminal,
        # or the AppTest harness. Nothing to gate.
        return

    if not hmac.compare_digest(supplied, EXPECTED):
        st.error("This page is served through butterfly.buckstoplabs.com.")
        st.caption("Direct requests to the Cloud Run URL are not accepted.")
        st.stop()
