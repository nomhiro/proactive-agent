import time

import jwt
import pytest

from proactive_functions.auth import AuthError
from tests.conftest import AUD, TENANT


def token(key, **claims):
    base = {"aud": AUD, "iss": f"https://login.microsoftonline.com/{TENANT}/v2.0", "tid": TENANT,
            "azp": "agent-ic", "exp": int(time.time()) + 600}
    return "Bearer " + jwt.encode(base | claims, key, algorithm="RS256")


def test_valid_token_returns_client_id(verifier, key):
    assert verifier.verify(token(key)) == "agent-ic"


def test_identifier_uri_audience_accepted(verifier, key):
    assert verifier.verify(token(key, aud=f"api://{TENANT}/gw")) == "agent-ic"


def test_v1_token_uses_appid(verifier, key):
    t = token(key, iss=f"https://sts.windows.net/{TENANT}/", azp=None, appid="agent-ev")
    assert verifier.verify(t) == "agent-ev"


@pytest.mark.parametrize("claims", [{"aud": "someone-else"}, {"iss": "https://evil/"}, {"tid": "x"},
                                    {"exp": int(time.time()) - 10}, {"azp": None}])
def test_bad_claims_rejected(verifier, key, claims):
    with pytest.raises(AuthError):
        verifier.verify(token(key, **claims))


@pytest.mark.parametrize("header", [None, "", "Basic abc", "Bearer not-a-jwt"])
def test_malformed_header_rejected(verifier, header):
    with pytest.raises(AuthError):
        verifier.verify(header)


def test_token_signed_by_other_key_rejected(verifier, other_key):
    with pytest.raises(AuthError):
        verifier.verify(token(other_key))


def test_hs256_token_rejected(verifier):
    claims = {"aud": AUD, "azp": "x", "exp": int(time.time()) + 600}
    t = "Bearer " + jwt.encode(claims, "secret-" * 8, algorithm="HS256")
    with pytest.raises(AuthError):
        verifier.verify(t)
