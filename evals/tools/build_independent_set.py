"""独立来源场景集的构建脚本（30 条，第三方编写）。

**这批场景不是 Agent 生成的，是第三方朋友独立编写的。**
我们只做三件必要的结构化处理，且必须在报告里声明：

1. 补 `subject` / `relation`：原作者用自然语言描述场景，没有字段名。
   我们按语义映射到已有的归一化词表（`package_manager`、`deploy_target` 等）。
2. 补 `existing_authority`：原作者用"谁说的"描述权威，
   我们映射为 `user_direct` / `third_party` / `system_inferred`。
   **这一步是必需的**：此前的评测把 existing 一律当成 user_direct，
   导致"第三方转述 vs 第三方转述"被误判成"低权威 vs 高权威"。
3. 补 `condition`：C3 不做条件抽取。原作者说"两种场景都对"时，
   我们从他给的原文里提取条件词（如"法定节假日"、"应酬"）。
   **这一步会高估系统能力**，因为真实使用时条件也要靠抽取。

除以上三点，`text` / `existing_value` / `candidate_value` / `expected` /
`rationale` / `confidence` 全部保留原作者原文。

运行：
    uv run python -m evals.tools.build_independent_set
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "data" / "conflict-set" / "independent.jsonl"

# (id, text, subject, relation, candidate, existing, expected,
#  authority, existing_authority, condition, existing_condition, rationale, confidence)
Case = tuple[
    str, str, str, str, str, str | None, str,
    str, str, str | None, str | None, str, str,
]

_UD = "user_direct"
_TP = "third_party"
_SI = "system_inferred"

CASES: list[Case] = [
    (
        "ind-01",
        "上线推迟了，老板说改到下周五。",
        "project:default", "launch_date", "下周五", "下周三",
        "SUPERSEDE", _TP, _UD, None, None,
        "原来的时间作废了，被新时间取代。", "确定",
    ),
    (
        "ind-02",
        "寄到朝阳区青年路23号院3号楼吧。",
        "user:default", "address", "朝阳区青年路23号院3号楼", "朝阳大悦城附近",
        "MERGE", _UD, _UD, None, None,
        "原记录的地址仍然成立，这次补充了具体的门牌号。", "确定",
    ),
    (
        "ind-03",
        "密码不是那个，应该是87654321吧。",
        "user:default", "wifi_password", "87654321", "12345678",
        "CONFLICT", _UD, _UD, None, None,
        "两个密码不一样，且看不出到底记错了哪个。", "确定",
    ),
    (
        "ind-04",
        "小李对花生过敏。",
        "user:xiaoli", "dietary_restriction", "对花生过敏", None,
        "ADD", _TP, _UD, None, None,
        "之前没有关于小李过敏的记录，这是新信息。", "确定",
    ),
    (
        "ind-05",
        "明年准备换个新能源车开开。",
        "user:default", "car_plan", "明年换新能源车", "明年换一辆新能源车",
        "NOOP", _UD, _UD, None, None,
        "意思和已记录的完全一样，只是又说了一遍。", "确定",
    ),
    (
        "ind-06",
        "逢法定节假日，周会就顺延到周二上午。",
        "department:default", "meeting_time", "周二上午", "周一上午",
        "BRANCH", _UD, _UD, "法定节假日", "平时",
        "平时和节假日两种场景都对，适用条件不同。", "确定",
    ),
    (
        "ind-07",
        "今天这杯美式太苦了，给我加点糖包。",
        "user:default", "coffee_sugar", "加糖", "从不加糖",
        "CONFLICT", _UD, _UD, None, None,
        "平时说从不加糖，今天又要加糖，行为矛盾且不知以哪个为准。", "不太确定",
    ),
    (
        "ind-08",
        "最近小区老丢件，快递放丰巢柜吧。",
        "user:default", "delivery_instruction", "放丰巢柜", "放门口",
        "SUPERSEDE", _UD, _UD, None, None,
        "之前的'放门口'指令作废，换成了新的投放方式。", "确定",
    ),
    (
        "ind-09",
        "昨天交的报销单少附了一张高铁票。",
        "user:default", "expense_status", "报销单少附一张高铁票", "已提交给财务",
        "MERGE", _UD, _UD, None, None,
        "提交的事实还在，补充了材料缺失的细节。", "不太确定",
    ),
    (
        "ind-10",
        "我下周去上海的航班号是MU5137。",
        "user:default", "flight_number", "MU5137", None,
        "ADD", _SI, _UD, None, None,
        "之前没有航班信息，属于全新记录。", "确定",
    ),
    (
        "ind-11",
        "咱们服务器每周日零点开始例行维护。",
        "infra:default", "maintenance_window", "每周日零点", "每周日凌晨",
        "NOOP", _TP, _UD, None, None,
        "周日零点就是周日凌晨，完全重复了同样的信息。", "不太确定",
    ),
    (
        "ind-12",
        "那只猫叫'橘子'，是个公猫。",
        "user:default", "pet_cat", "猫叫橘子是公猫", "养了一只猫",
        "MERGE", _UD, _UD, None, None,
        "养猫的事实不变，增加了名字和性别。", "确定",
    ),
    (
        "ind-13",
        "feature-A上的代码还没合，现在master跑不通。",
        "repo:default", "merge_status", "feature-A 未合且 master 跑不通", "都合并到 master",
        "CONFLICT", _TP, _UD, None, None,
        "一边说都合并了，一边说还有没合并的，状态矛盾。", "不太确定",
    ),
    (
        "ind-14",
        "要是跟客户应酬，中午就吃淮扬菜。",
        "user:default", "lunch_habit", "淮扬菜", "轻食",
        "BRANCH", _UD, _UD, "客户应酬", "日常",
        "日常和应酬两种不同场景下的习惯，互不冲突。", "确定",
    ),
    (
        "ind-15",
        "那个号不用了，换了13987654321。",
        "user:default", "phone_number", "13987654321", "13812345678",
        "SUPERSEDE", _UD, _UD, None, None,
        "旧号码作废，被新号码替代。", "确定",
    ),
    (
        "ind-16",
        "我今年体检尿酸有点偏高。",
        "user:default", "health_metric", "尿酸偏高", None,
        "ADD", _UD, _UD, None, None,
        "全新的个人健康信息记录。", "确定",
    ),
    (
        "ind-17",
        "就是C区第三排左数第二个工位。",
        "user:default", "seat", "C区第三排左数第二个工位", "靠窗那一排",
        "MERGE", _UD, _UD, None, None,
        "大位置没变，补充了精确的工位号。", "确定",
    ),
    (
        "ind-18",
        "下周六咱们部门去怀柔玩。",
        "department:default", "team_building", "下周六去怀柔", "下周六去怀柔团建",
        "NOOP", _TP, _UD, None, None,
        "就是重复了一遍团建的时间和地点。", "确定",
    ),
    (
        "ind-19",
        "不可能，我书架上没看到《三体》。",
        "user:default", "book_return", "没收到《三体》", "已还《三体》",
        "CONFLICT", _TP, _UD, None, None,
        "一方说还了，一方说没收到，完全矛盾。", "确定",
    ),
    (
        "ind-20",
        "财务系统升级，这批退款得下周才能处理。",
        "order:default", "refund_eta", "下周才能处理", "3-5 个工作日到账",
        "SUPERSEDE", _TP, _UD, None, None,
        "原来到账时间的承诺作废，更新了新的进度。", "确定",
    ),
    (
        "ind-21",
        "送孩子上学的日子，我得9点半才能到。",
        "user:default", "arrival_time", "9点半", "9点",
        "BRANCH", _UD, _UD, "送孩子上学", "平时",
        "平时和送孩子上学日，两种情况对应不同的到达时间。", "确定",
    ),
    (
        "ind-22",
        "是16寸的，M2 Max芯片，1TB硬盘。",
        "user:default", "laptop_spec", "16寸 M2 Max 1TB", "配了台新MacBook",
        "MERGE", _UD, _UD, None, None,
        "电脑本身的事实不变，补充了具体配置参数。", "确定",
    ),
    (
        "ind-23",
        "气象台刚更新了，周末晴转多云，没雨。",
        "weather:default", "weekend_forecast", "晴转多云", "有暴雨",
        "SUPERSEDE", _TP, _UD, None, None,
        "旧的天气预报被新的天气预报覆盖了。", "确定",
    ),
    (
        "ind-24",
        "记得在结婚纪念日定一束红玫瑰。",
        "user:default", "anniversary_reminder", "纪念日订红玫瑰", None,
        "ADD", _UD, _UD, None, None,
        "之前没记过，属于新增的备忘。", "确定",
    ),
    (
        "ind-25",
        "刚刚把Steam账号换绑成新邮箱了。",
        "user:default", "steam_email", "新邮箱", "旧邮箱",
        "SUPERSEDE", _SI, _UD, None, None,
        "绑定的邮箱从旧的变成了新的，原记录失效。", "确定",
    ),
    (
        "ind-26",
        "周末要是回爸妈家，就不做饭了。",
        "user:default", "weekend_cooking", "不做饭", "自己做饭",
        "BRANCH", _UD, _UD, "回爸妈家", "在自己家",
        "在自己家和回父母家两种不同场景下的行为。", "确定",
    ),
    (
        "ind-27",
        "我们开会一般也都用腾讯会议。",
        "team:default", "meeting_tool", "腾讯会议", "腾讯会议",
        "NOOP", _TP, _UD, None, None,
        "完全一样的意思，重复表述。", "确定",
    ),
    (
        "ind-28",
        "我上个月打车花了150，财务也全给报了。",
        "company:default", "taxi_reimbursement", "150 也全报了", "上限每晚100元",
        "CONFLICT", _UD, _UD, None, None,
        "制度说是100上限，实际却报了150，不知是制度变了还是特批。", "不太确定",
    ),
    (
        "ind-29",
        "我刚把手机锁屏密码改成1024了。",
        "user:default", "screen_lock_password", "1024", "0810",
        "SUPERSEDE", _UD, _UD, None, None,
        "旧密码作废，替换成了新密码。", "确定",
    ),
    (
        "ind-30",
        "主要是虾和蟹不行，吃鱼没事。",
        "user:default", "dietary_restriction", "虾蟹不行鱼没事", "吃海鲜起疹子",
        "MERGE", _UD, _UD, None, None,
        "海鲜过敏的大前提不变，细化了具体过敏的种类。", "确定",
    ),
]


def _to_dict(case: Case) -> dict[str, object]:
    (
        case_id, text, subject, relation, candidate, existing, expected,
        authority, existing_authority, condition, existing_condition, rationale, confidence,
    ) = case
    payload: dict[str, object] = {
        "id": case_id,
        "text": text,
        "subject": subject,
        "relation": relation,
        "candidate_value": candidate,
        "existing_value": existing,
        "expected": expected,
        "authority": authority,
        "existing_authority": existing_authority,
        "rationale": rationale,
        "confidence": confidence,
        "source": "friend",
    }
    if condition:
        payload["condition"] = condition
    if existing_condition:
        payload["existing_condition"] = existing_condition
    return payload


def main() -> int:
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(_to_dict(case), ensure_ascii=False) for case in CASES]
    TARGET.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{TARGET.name}: {len(CASES)} 条（第三方独立编写）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
