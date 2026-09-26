"""仪表校准判定规则的回归测试：到期口径、保存拦截、记录去重与台账一致性。"""
from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient

from app.main import app
from app.services.meter import evaluate, threshold_for
from app.store import store

client = TestClient(app)

# 与种子数据对齐的固定“今天”，保证断言不随真实日期漂移
TODAY = date(2026, 9, 26)


def ledger_row(code: str) -> dict:
    for row in store.rows("meter"):
        if row.get("仪表编号") == code:
            return row
    raise AssertionError(f"种子数据缺少 {code}")


def test_threshold_follows_location() -> None:
    assert threshold_for("出水口在线间") == 45
    assert threshold_for("排放口") == 45
    assert threshold_for("进水口计量井") == 30
    assert threshold_for("化验室") == 15
    assert threshold_for("曝气池") == 30  # 未配置的位置走默认 30 天


def test_due_within_threshold_marked_pending() -> None:
    view = evaluate(ledger_row("METE-0002"), TODAY)
    assert view["仪表状态"] == "待校准"
    assert view["剩余天数"] == 14
    assert view["预警阈值"] == 30
    assert "待校准" in view["判定结论"] or "阈值" in view["判定结论"]


def test_location_threshold_relaxes_lab() -> None:
    # 化验室阈值 15 天：剩 24 天不触发，默认 30 天口径会误判
    view = evaluate(ledger_row("METE-0004"), TODAY)
    assert view["剩余天数"] == 24
    assert view["预警阈值"] == 15
    assert view["仪表状态"] == "正常"


def test_location_threshold_tightens_outlet() -> None:
    # 出水口阈值 45 天：剩 40 天触发，默认 30 天口径会漏判
    view = evaluate(ledger_row("METE-0005"), TODAY)
    assert view["剩余天数"] == 40
    assert view["预警阈值"] == 45
    assert view["仪表状态"] == "待校准"


def test_exempt_statuses_skip_evaluation() -> None:
    stopped = evaluate(ledger_row("METE-0006"), TODAY)
    assert stopped["仪表状态"] == "已停用"  # 校准已过期也不参与判定
    assert stopped["pending"] is False
    scrapped = evaluate(ledger_row("METE-0007"), TODAY)
    assert scrapped["仪表状态"] == "已报废"
    assert "不参与到期判定" in scrapped["判定结论"]


def test_latest_calibration_record_wins() -> None:
    # METE-0003 有两条校准记录，旧记录已过期，应以 2026-08-25 那条为准
    view = evaluate(ledger_row("METE-0003"), TODAY)
    assert view["最近校准日"] == "2026-08-25"
    assert view["下次校准日"] == "2027-08-25"
    assert view["仪表状态"] == "正常"


def test_overdue_marked_pending_and_abnormal() -> None:
    view = evaluate(ledger_row("METE-0008"), TODAY)
    assert view["仪表状态"] == "待校准"
    assert view["剩余天数"] == -1
    assert view["abnormal"] is True


def test_range_mismatch_in_use_flagged() -> None:
    view = evaluate(ledger_row("METE-0009"), TODAY)
    assert view["量程核验"] == "不符"
    assert view["abnormal"] is True
    assert "量程核验不符" in view["判定结论"]


def test_reject_last_calibration_after_next() -> None:
    response = client.post("/api/meter", json={"values": {
        "仪表编号": "METE-T001",
        "仪表名称": "测试仪表",
        "安装位置": "化验室",
        "最近校准日": "2026-09-30",
        "下次校准日": "2026-09-01",
    }})
    payload = response.json()
    assert payload["ok"] is False
    assert "晚于下次校准日" in payload["message"]
    assert all(row.get("仪表编号") != "METE-T001" for row in store.rows("meter"))


def test_reject_range_mismatch_in_use_on_create() -> None:
    response = client.post("/api/meter", json={"values": {
        "仪表编号": "METE-T002",
        "仪表名称": "测试仪表",
        "安装位置": "进水口",
        "最近校准日": "2026-09-01",
        "下次校准日": "2027-09-01",
        "量程核验": "不符",
    }})
    payload = response.json()
    assert payload["ok"] is False
    assert "量程核验不符" in payload["message"]


def test_reject_range_mismatch_in_use_on_calibrate() -> None:
    response = client.post("/api/meter/1/actions", json={"values": {
        "action": "校准登记",
        "校准日期": "2026-09-26",
        "下次校准日": "2027-09-26",
        "量程核验": "不符",
    }})
    payload = response.json()
    assert payload["ok"] is False
    assert "量程核验不符" in payload["message"]


def test_calibrate_flow_uses_latest_record() -> None:
    created = client.post("/api/meter", json={"values": {
        "仪表编号": "METE-T003",
        "仪表名称": "测试流量计",
        "安装位置": "进水口",
        "最近校准日": "2026-09-01",
        "下次校准日": "2026-10-05",
    }}).json()
    assert created["ok"] is True
    entry_id = created["entry"]["id"]
    assert created["entry"]["仪表状态"] == "待校准"  # 剩 9 天，低于进水口 30 天阈值

    done = client.post(f"/api/meter/{entry_id}/actions", json={"values": {
        "action": "校准登记",
        "校准日期": "2026-09-26",
        "下次校准日": "2027-09-26",
        "登记人": "测试员",
    }}).json()
    assert done["ok"] is True
    assert done["entry"]["仪表状态"] == "正常"

    records = client.get(f"/api/meter/{entry_id}/calibrations").json()
    adopted = [item for item in records["items"] if item["是否采用"]]
    assert len(records["items"]) == 2
    assert len(adopted) == 1
    assert adopted[0]["校准日期"] == "2026-09-26"


def test_ledger_and_detail_agree() -> None:
    listed = client.get("/api/meter", params={"keyword": "METE-0005"}).json()["items"]
    assert len(listed) == 1
    detail = client.get(f"/api/meter/{listed[0]['id']}").json()
    for field in ("仪表状态", "判定结论", "剩余天数", "预警阈值", "下次校准日"):
        assert listed[0][field] == detail[field]


def test_recalculate_remarks_existing_rows() -> None:
    payload = client.post("/api/meter/recalculate").json()
    assert payload["ok"] is True
    row = ledger_row("METE-0002")
    assert row["仪表状态"] == "待校准"
    assert row["pending"] is True
    stats = client.get("/api/meter/stats").json()
    assert stats["total"] == payload["entry"]["total"]
    assert stats["待校准"] >= 1


def test_status_filter_uses_derived_status() -> None:
    items = client.get("/api/meter", params={"status": "已停用"}).json()["items"]
    assert items and all(item["仪表状态"] == "已停用" for item in items)
