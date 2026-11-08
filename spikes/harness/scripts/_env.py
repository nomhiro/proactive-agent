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
