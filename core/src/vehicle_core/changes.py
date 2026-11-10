"""変更イベントの中身を、開発データの文書に当てる（シナリオの再生が artifacts を更新するのに使う）。"""

import copy
from datetime import datetime

from .clock import to_jst
from .models import FieldChange


def apply_changes(doc: dict, changes: list[FieldChange], at: datetime) -> dict:
    """path は `attributes.period_ms` のような `.` 区切り。新しい辞書を返し、元の文書は変えない。"""
    out = copy.deepcopy(doc)
    for change in changes:
        *parents, leaf = change.path.split(".")
        node = out
        for key in parents:
            if not isinstance(node.get(key), dict):
                node[key] = {}
            node = node[key]
        node[leaf] = copy.deepcopy(change.after)
    out["updated_at"] = to_jst(at).isoformat()
    return out
