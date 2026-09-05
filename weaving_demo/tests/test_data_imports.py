import base64
from io import BytesIO

from openpyxl import Workbook
import pytest

from weaving_demo.data_imports import DataImportStore, REQUIRED_SHEETS


def _book_base64(sheet_names):
    wb = Workbook()
    wb.remove(wb.active)
    for name in sheet_names:
        ws = wb.create_sheet(name)
        ws.append(["字段", "值"])
        ws.append(["测试", 1])
    out = BytesIO()
    wb.save(out)
    return base64.b64encode(out.getvalue()).decode("ascii")


def test_import_preview_blocks_missing_required_sheets(tmp_path):
    store = DataImportStore(tmp_path / "imports")
    result = store.preview("test.xlsx", _book_base64(["①基础资料"]), {"products": 10})

    assert result["status"] == "BLOCKED"
    assert not result["can_save"]
    assert result["error_count"] == len(REQUIRED_SHEETS) - 1
    assert any(x["code"] == "MISSING_SHEET" for x in result["issues"])


def test_import_preview_and_snapshot_history(tmp_path):
    store = DataImportStore(tmp_path / "imports")
    preview = store.preview("完整模板.xlsx", _book_base64(REQUIRED_SHEETS), {
        "products": 0, "looms": 0, "tasks": 0, "warps": 0, "materials": 0,
    })

    assert preview["status"] == "READY"
    assert preview["can_save"]
    assert preview["sheet_count"] == len(REQUIRED_SHEETS)
    saved = store.save_snapshot(preview["preview_id"], "候选数据")
    assert saved["status"] == "SAVED_NOT_ACTIVE"
    assert saved["active"] is False
    history = store.list_snapshots()
    assert history["count"] == 1
    assert history["snapshots"][0]["snapshot_id"] == saved["snapshot_id"]
    assert history["active_snapshot_id"] is None


def test_blocked_preview_cannot_be_saved(tmp_path):
    store = DataImportStore(tmp_path / "imports")
    preview = store.preview("test.xlsx", _book_base64(["①基础资料"]), {})
    with pytest.raises(ValueError, match="阻断"):
        store.save_snapshot(preview["preview_id"])


def test_import_preview_rejects_non_excel(tmp_path):
    store = DataImportStore(tmp_path / "imports")
    with pytest.raises(ValueError, match="仅支持"):
        store.preview("test.csv", base64.b64encode(b"a,b").decode("ascii"), {})
