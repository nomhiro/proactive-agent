"""書き込み窓口に来た Entra ID のトークンを検証し、呼び出し元の client ID を返す。

許可の根拠は client ID と team_settings.agent_client_id の対応表だけにする（roles は見ない）。
既定ではテナント内のどのアプリもこの API 宛てのトークンを取れるため。
"""

from typing import Protocol

import jwt
from jwt import PyJWKClient


class AuthError(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class TokenVerifier(Protocol):
    def verify(self, authorization: str | None) -> str: ...


class EntraTokenVerifier:
    def __init__(self, tenant_id: str, audiences: list[str], jwks_client: PyJWKClient | None = None) -> None:
        self._tenant = tenant_id
        self._audiences = audiences
        self._issuers = {
            f"https://login.microsoftonline.com/{tenant_id}/v2.0",
            f"https://sts.windows.net/{tenant_id}/",
        }
        self._jwks = jwks_client or PyJWKClient(
            f"https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys", cache_keys=True)

    def verify(self, authorization: str | None) -> str:
        if not authorization or not authorization.startswith("Bearer "):
            raise AuthError("Bearer トークンがありません")
        token = authorization.removeprefix("Bearer ").strip()
        try:
            key = self._jwks.get_signing_key_from_jwt(token).key
            claims = jwt.decode(token, key, algorithms=["RS256"], audience=self._audiences,
                                options={"require": ["exp", "aud", "iss"]})
        except jwt.PyJWTError as e:
            raise AuthError(f"トークンを検証できません（{type(e).__name__}）") from None
        if claims.get("iss") not in self._issuers or claims.get("tid") != self._tenant:
            raise AuthError("トークンの発行元が違います")
        client_id = claims.get("azp") or claims.get("appid")
        if not client_id:
            raise AuthError("トークンに呼び出し元のアプリがありません")
        return client_id
