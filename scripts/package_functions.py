"""Functions をデプロイ用に整える（azd のフックから呼ぶ）。

prepare: core の vehicle_core を functions/ に写し、requirements.txt を作る
cleanup: 写しを消す

Flex Consumption はリモートで `pip install -r requirements.txt` するので、
uv ワークスペースの vehicle-core はそのままでは入らない。そのためソースを写す。
"""

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FUNCTIONS = ROOT / "functions"
CORE_SRC = ROOT / "core" / "src" / "vehicle_core"
COPY = FUNCTIONS / "vehicle_core"
REQUIREMENTS = FUNCTIONS / "requirements.txt"


def prepare() -> None:
    cleanup()
    shutil.copytree(CORE_SRC, COPY, ignore=shutil.ignore_patterns("__pycache__"))
    subprocess.run(
        ["uv", "export", "--package", "proactive-functions", "--no-dev", "--no-hashes",
         "--no-emit-workspace", "--frozen", "--no-header", "--quiet", "-o", str(REQUIREMENTS)],
        cwd=ROOT, check=True,
    )
    print(f"prepared: {COPY.relative_to(ROOT)}, {REQUIREMENTS.relative_to(ROOT)}")


def cleanup() -> None:
    if COPY.exists():
        shutil.rmtree(COPY)
    print(f"cleaned: {COPY.relative_to(ROOT)}")


if __name__ == "__main__":
    commands = {"prepare": prepare, "cleanup": cleanup}
    if len(sys.argv) != 2 or sys.argv[1] not in commands:
        sys.exit("usage: package_functions.py prepare|cleanup")
    commands[sys.argv[1]]()
