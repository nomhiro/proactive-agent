"""Azure Functions のトリガー定義。どの関数も、本体（proactive_functions）を呼ぶだけにする。"""

import json

import azure.functions as func
from vehicle_core.constants import VEHICLE_ID

app = func.FunctionApp()


def _health() -> func.HttpResponse:
    body = {"ok": True, "vehicle_id": VEHICLE_ID}
    return func.HttpResponse(json.dumps(body), status_code=200, mimetype="application/json")


@app.route(route="health", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def health(req: func.HttpRequest) -> func.HttpResponse:
    return _health()
