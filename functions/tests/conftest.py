from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

TENANT = "11111111-1111-1111-1111-111111111111"
AUD = "22222222-2222-2222-2222-222222222222"


def _rsa():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="session")
def key():
    return _rsa()


@pytest.fixture(scope="session")
def other_key():
    return _rsa()


class FakeJwks:
    """PyJWKClient の偽物。どのトークンにも key の公開鍵を返す。"""

    def __init__(self, private_key) -> None:
        self._public = private_key.public_key()

    def get_signing_key_from_jwt(self, token):
        return SimpleNamespace(key=self._public)


@pytest.fixture
def verifier(key):
    from proactive_functions.auth import EntraTokenVerifier
    return EntraTokenVerifier(TENANT, [AUD, f"api://{TENANT}/gw"], jwks_client=FakeJwks(key))
