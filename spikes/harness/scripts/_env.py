"""azd の環境の値を読む（azd env get-values）。spikes/harness で実行する前提。"""

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp"))
# Windows でも見つかるよう、実行ファイルの場所を先に探す
AZD = shutil.which("azd") or "azd"


def azd_env() -> dict[str, str]:
    out = subprocess.run([AZD, "env", "get-values"], cwd=ROOT, check=True, capture_output=True, text=True).stdout
    values = {}
    for line in out.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            values[k.strip()] = v.strip().strip('"')
    return values


# --- Plan 3 Task 1 の確認で共通に使うもの ---------------------------------
AZ = shutil.which("az") or "az"
RESULTS = ROOT / "results"


def save(name: str, data) -> Path:
    import json
    from datetime import datetime
    RESULTS.mkdir(exist_ok=True)
    path = RESULTS / f"{datetime.now():%Y%m%d-%H%M%S}-{name}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"saved: {path}")
    return path


def project_client(env: dict):
    from azure.ai.projects import AIProjectClient
    from azure.identity import DefaultAzureCredential
    return AIProjectClient(endpoint=env["FOUNDRY_PROJECT_ENDPOINT"], credential=DefaultAzureCredential(),
                           allow_preview=True)


def assign_role(principal_id: str, role_id: str, scope: str) -> str:
    """サービスプリンシパルにロールを付ける。既にあれば何もしない（az CLI に JSON は渡さない）。"""
    r = subprocess.run([AZ, "role", "assignment", "create", "--assignee-object-id", principal_id,
                        "--assignee-principal-type", "ServicePrincipal", "--role", role_id, "--scope", scope,
                        "-o", "none"], capture_output=True, text=True)
    if r.returncode != 0 and "RoleAssignmentExists" not in r.stderr:
        raise RuntimeError(r.stderr)
    return "exists" if r.returncode != 0 else "created"


def arm(method: str, url: str, body: dict | None = None) -> dict:
    """ARM の REST を自分の ID で呼ぶ（RAI ポリシーや接続など、SDK にないもの）。"""
    import json
    import urllib.error
    import urllib.request
    from azure.identity import DefaultAzureCredential
    token = DefaultAzureCredential().get_token("https://management.azure.com/.default").token
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as res:
            raw = res.read()
            return {"status": res.status, "body": json.loads(raw) if raw else None}
    except urllib.error.HTTPError as e:
        return {"status": e.code, "body": e.read().decode("utf-8", "replace")}


def agent_identity(project, name: str) -> dict:
    return project.agents.get(name).as_dict().get("instance_identity") or {}


def queue_probe(env: dict, message: dict, timeout_s: int = 900) -> dict:
    """Functions（マネージド ID）に確認を頼み、probe-results/<id>.json を待つ。"""
    import json
    import time
    import uuid
    from azure.core.exceptions import ResourceNotFoundError
    from azure.identity import DefaultAzureCredential
    from azure.storage.blob import BlobClient
    from azure.storage.queue import QueueClient

    probe_id = uuid.uuid4().hex
    account = f"https://{env['STORAGE_ACCOUNT_NAME']}"
    credential = DefaultAzureCredential()
    QueueClient(f"{account}.queue.core.windows.net", "probe", credential=credential).send_message(
        json.dumps({"id": probe_id, **message}, ensure_ascii=False))
    blob = BlobClient(f"{account}.blob.core.windows.net", "probe-results", f"{probe_id}.json", credential=credential)
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            return json.loads(blob.download_blob().readall())
        except ResourceNotFoundError:
            time.sleep(10)
    raise SystemExit(f"timed out waiting for probe-results/{probe_id}.json")
