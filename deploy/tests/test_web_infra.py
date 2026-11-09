"""Web の Bicep（infra/modules/web.bicep）を組み立てた結果を確かめる。az がなければ飛ばす。"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

WEB_BICEP = Path(__file__).resolve().parents[2] / "infra" / "modules" / "web.bicep"
DEFAULT_APP_ROLE = "00000000-0000-0000-0000-000000000000"


@pytest.fixture(scope="module")
def template(tmp_path_factory) -> dict:
    az = shutil.which("az")
    if az is None:
        pytest.skip("az がない")
    out = tmp_path_factory.mktemp("bicep") / "web.json"  # 標準出力は Windows で cp932 になるのでファイルに書かせる
    subprocess.run([az, "bicep", "build", "--file", str(WEB_BICEP), "--outfile", str(out)], check=True,
                   capture_output=True)
    return json.loads(out.read_text(encoding="utf-8"))


def _resources(template: dict) -> dict:
    res = template["resources"]
    return res if isinstance(res, dict) else {r["name"]: r for r in res}


def _of_type(template: dict, prefix: str) -> list[dict]:
    return [r for r in _resources(template).values() if r["type"].startswith(prefix)]


def test_sign_in_requires_assignment_when_deployer_is_known(template):  # 最終レビュー Important 7
    assert "principalId" in template["parameters"]
    [sp] = _of_type(template, "Microsoft.Graph/servicePrincipals")
    assert "principalId" in str(sp["properties"]["appRoleAssignmentRequired"])


def test_deployer_is_assigned_to_sign_in_app(template):  # 最終レビュー Important 7
    [assignment] = _of_type(template, "Microsoft.Graph/appRoleAssignedTo")
    props = assignment["properties"]
    assert props["appRoleId"] == DEFAULT_APP_ROLE
    assert "principalId" in str(props["principalId"])
    assert "principalId" in str(assignment.get("condition", ""))
