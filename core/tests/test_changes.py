from datetime import datetime

from vehicle_core.changes import apply_changes
from vehicle_core.constants import JST
from vehicle_core.models import FieldChange

AT = datetime(2026, 11, 17, 21, 10, tzinfo=JST)


def test_apply_changes_sets_nested_path_and_updated_at():
    doc = {"id": "SIG-BrkPedalPos", "attributes": {"period_ms": 10, "sender": "VCU"}, "updated_at": "x"}
    out = apply_changes(doc, [FieldChange(path="attributes.period_ms", before=10, after=20)], AT)
    assert out["attributes"] == {"period_ms": 20, "sender": "VCU"}
    assert out["updated_at"] == AT.isoformat()
    assert doc["attributes"]["period_ms"] == 10  # 元の文書は変えない


def test_apply_changes_sets_top_level_field():
    out = apply_changes({"id": "SPEC-BRK-04", "description": "旧"},
                        [FieldChange(path="description", before="旧", after="新")], AT)
    assert out["description"] == "新"


def test_apply_changes_creates_missing_parent():
    out = apply_changes({"id": "X"}, [FieldChange(path="attributes.a", before=None, after=1)], AT)
    assert out["attributes"] == {"a": 1}
