# tests/test_competition.py
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from unittest.mock import AsyncMock, patch

from competition import generate_challenge_code, verify_liveness_response


def test_generate_challenge_code_is_4_digits():
    code = generate_challenge_code()
    assert len(code) == 4
    assert code.isdigit()


def test_generate_challenge_code_varies():
    codes = {generate_challenge_code() for _ in range(20)}
    assert len(codes) > 1  # not always the same


def test_verify_liveness_true():
    assert verify_liveness_response('{"code_visible": true}', "4823") is True


def test_verify_liveness_false():
    assert verify_liveness_response('{"code_visible": false}', "4823") is False


def test_verify_liveness_parse_error():
    assert verify_liveness_response("not json", "4823") is False


def test_verify_liveness_missing_field():
    assert verify_liveness_response('{"other": "stuff"}', "4823") is False


def test_verify_liveness_null():
    assert verify_liveness_response(None, "4823") is False
