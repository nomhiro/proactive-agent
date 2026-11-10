"""サインインした利用者（決定 2）。

Container Apps の組み込み認証は、サインインした人の名前を X-MS-CLIENT-PRINCIPAL-NAME で渡す。
外から同じヘッダーを付けても、組み込み認証が取り除く。WEB_AUTH=off（ローカル）だけは「local」とみなす。
"""

from collections.abc import Mapping

PRINCIPAL_HEADER = "x-ms-client-principal-name"


def current_user(headers: Mapping[str, str], mode: str) -> str | None:
    if mode == "off":
        return "local"
    value = headers.get(PRINCIPAL_HEADER)
    return value.strip() if value and value.strip() else None
