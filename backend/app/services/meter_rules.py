"""仪表校准判定规则：阈值口径、日期/量程校验与到期结论都收在这里。

判定口径（上线后全平台统一，台账列表与仪表详情共用同一函数）：
1. 下次校准日距今天不足该安装位置对应阈值天数的，自动标为「待校准」；
2. 停用与报废的仪表不参与到期判定，结论分别给「停用中」「已报废」；
3. 已手动登记漂移预警但尚未到期的，结论给「漂移预警」；
4. 其余在用仪表结论为「正常」。

阈值按安装位置区分，未配置的位置走默认阈值（30 天）。
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

# 默认到期阈值：距下次校准日不足 30 天即待校准
DEFAULT_THRESHOLD_DAYS = 30

# 各安装位置的专属阈值（天）。关键工艺点位校准要求更密/更疏都在这里配置。
LOCATION_THRESHOLDS: dict[str, int] = {
    "进水仪表间": 45,
    "出水在线监测站": 45,
    "鼓风机房": 15,
}

# 不参与到期判定的生命周期状态
EXCLUDED_LIFECYCLE = {"停用", "报废"}

STATUS_NORMAL = "正常"
STATUS_DRIFT = "漂移预警"
STATUS_PENDING = "待校准"
STATUS_STOPPED = "停用中"
STATUS_SCRAPPED = "已报废"

# 台账「仪表状态」允许出现的全部结论
VERDICTS = [STATUS_NORMAL, STATUS_DRIFT, STATUS_PENDING, STATUS_STOPPED, STATUS_SCRAPPED]

# 生命周期状态（仪表自身的在用情况）与结论的映射
LIFECYCLE_VERDICT = {"停用": STATUS_STOPPED, "报废": STATUS_SCRAPPED}


def threshold_for(location: Any) -> int:
    """按安装位置取到期阈值；位置未单独配置时使用默认 30 天。"""
    key = str(location or "").strip()
    return LOCATION_THRESHOLDS.get(key, DEFAULT_THRESHOLD_DAYS)


def parse_date(value: Any) -> date | None:
    """宽松解析 YYYY-MM-DD 等常见日期写法；解析不了返回 None，由调用方决定是否放行。"""
    if value is None:
        return None
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y%m%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def normalize_range(value: Any) -> str:
    """归一化量程写法：去空白、统一连接符，便于跨记录比对。

    例如 "0 ~ 20 mg/L" 与 "0-20mg/L" 视为同一量程。
    """
    text = str(value or "").strip()
    for sign in ("～", "~", "—", "–", "至"):
        text = text.replace(sign, "-")
    return "".join(text.split())


def ranges_match(left: Any, right: Any) -> bool:
    """判断两次登记的量程是否一致；两边都没填时认为没有可比口径，按一致处理。"""
    a = normalize_range(left)
    b = normalize_range(right)
    if not a or not b:
        return True
    return a == b


def days_until(value: Any, *, today: date | None = None) -> int | None:
    """下次校准日距今天的天数；日期无法识别时返回 None。"""
    target = parse_date(value)
    if target is None:
        return None
    return (target - (today or date.today())).days


def evaluate_meter(meter: dict[str, Any], *, today: date | None = None) -> dict[str, Any]:
    """按统一口径计算单台仪表的校准结论。

    返回结论、剩余天数、适用阈值与判定原因；调用方负责写回/展示，本函数不改入参。
    """
    today = today or date.today()
    lifecycle = str(meter.get("生命周期状态") or "在用").strip() or "在用"
    location = meter.get("安装位置")
    threshold = threshold_for(location)

    if lifecycle in LIFECYCLE_VERDICT:
        verdict = LIFECYCLE_VERDICT[lifecycle]
        return {
            "verdict": verdict,
            "remaining_days": None,
            "threshold_days": threshold,
            "reason": f"仪表已{lifecycle}，不参与到期判定",
        }

    remaining = days_until(meter.get("下次校准日"), today=today)
    if remaining is None:
        # 日期缺失或无法识别：不能当作「正常」放过，提示补录校准信息。
        return {
            "verdict": STATUS_PENDING,
            "remaining_days": None,
            "threshold_days": threshold,
            "reason": "下次校准日缺失或格式无法识别，需补录校准信息",
        }

    if remaining < 0:
        return {
            "verdict": STATUS_PENDING,
            "remaining_days": remaining,
            "threshold_days": threshold,
            "reason": f"下次校准日已逾期 {-remaining} 天（{meter.get('安装位置')}阈值 {threshold} 天）",
        }

    if remaining < threshold:
        return {
            "verdict": STATUS_PENDING,
            "remaining_days": remaining,
            "threshold_days": threshold,
            "reason": (
                f"距下次校准日还有 {remaining} 天，不足 {meter.get('安装位置')} "
                f"{threshold} 天阈值"
            ),
        }

    if bool(meter.get("漂移标记")):
        return {
            "verdict": STATUS_DRIFT,
            "remaining_days": remaining,
            "threshold_days": threshold,
            "reason": f"已登记漂移预警，距下次校准日还有 {remaining} 天",
        }

    return {
        "verdict": STATUS_NORMAL,
        "remaining_days": remaining,
        "threshold_days": threshold,
        "reason": f"距下次校准日还有 {remaining} 天，满足 {threshold} 天阈值要求",
    }


def validate_calibration(
    record: dict[str, Any],
    meter: dict[str, Any] | None,
    *,
    today: date | None = None,
) -> list[str]:
    """校准记录保存前的硬校验；返回拒绝原因列表，空列表代表允许保存。

    - 仪表编号必须在台账中存在；
    - 校准日期、下次校准日必须是合法日期；
    - 最近校准日晚于下次校准日的不允许保存，并说明原因；
    - 量程与台账不符且仪表仍在用的必须拦下；停用/报废后允许登记历史记录。
    """
    today = today or date.today()
    errors: list[str] = []

    meter_no = str(record.get("仪表编号") or "").strip()
    if not meter_no:
        return ["仪表编号不能为空"]
    if meter is None:
        return [f"仪表编号 {meter_no} 不在仪表台账中，请先登记仪表"]

    calibrated_on = parse_date(record.get("校准日期"))
    next_on = parse_date(record.get("下次校准日"))
    if calibrated_on is None:
        errors.append("校准日期缺失或格式不正确，应为 YYYY-MM-DD")
    if next_on is None:
        errors.append("下次校准日缺失或格式不正确，应为 YYYY-MM-DD")
    if calibrated_on is not None and next_on is not None and calibrated_on > next_on:
        errors.append(
            f"最近校准日（{calibrated_on.isoformat()}）晚于下次校准日"
            f"（{next_on.isoformat()}），校准周期不成立，数据不允许保存"
        )

    if not ranges_match(record.get("校准时量程"), meter.get("仪表量程")):
        lifecycle = str(meter.get("生命周期状态") or "在用").strip() or "在用"
        if lifecycle not in EXCLUDED_LIFECYCLE:
            errors.append(
                f"校准时量程「{record.get('校准时量程')}」与台账量程「{meter.get('仪表量程')}」"
                "不符且该仪表仍在使用，必须先停用或更正量程后再登记"
            )

    return errors
