"""
competition.py — Skin competition helpers: challenge code generation and liveness check.
"""
import random
import json


def generate_challenge_code() -> str:
    """Return a random 4-digit string, e.g. '4823'."""
    return str(random.randint(1000, 9999))


def verify_liveness_response(raw_response, expected_code: str) -> bool:
    """
    Parse the vision model's liveness check response.
    Returns True only if {"code_visible": true} is present.
    expected_code is accepted for future fuzzy-match extension but unused in v1.
    """
    if raw_response is None:
        return False
    try:
        if isinstance(raw_response, str):
            data = json.loads(raw_response.strip())
        else:
            data = raw_response
        return bool(data.get("code_visible", False))
    except Exception:
        return False
