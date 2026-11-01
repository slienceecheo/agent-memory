"""所有 v2 结果文件必须同指纹——包括消融结果。

**为什么需要**：这一路出现过两次"数字对不上却查不出原因"，
两次都是结果文件缺元数据：

| # | 现象 | 靠什么查清 |
|---|---|---|
| 1 | `{1:33}` vs `{1:29,2:4}` | `git log` + `run_count` |
| 2 | 11 份结果文件混三次代码状态 | `code_diff_hash` |

而**消融文件此前完全没有元数据**——连 `run_count` 都没有。
它的产出（`0.3000` / `0.6000` / `0.2222` / `0.7778`）被四条结论里的三条引用：

- 结论 2（A 轴 = base + condition）用 `0.3000` / `0.9000`
- 结论 4（authority 临界点）间接依赖
- F20 门禁用 `0.6000` 与阈值 `0.3` 比较

所以"0.3000 是哪个版本测的"必须可复算，否则"推翻旧解读"这件事本身无法被验证。

**历史文件例外**：`v2-sample-lexical.json` 与 `v2-sample-lexical-text.json`
是样例期的旧产物（`8b1b600-dirty`），保留作为历史证据，不参与统一。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results"

# 必须统一指纹的当前有效结果
CURRENT = [
    "v2-ledger-lexical.json",
    "v2-ledger-vector.json",
    "v2-ledger-lexical-vector.json",
    "v2-ledger-vector-adjacency.json",
    "v2-ledger-lexical-vector-adjacency.json",
    "v2-sample-threeway.json",
    "v2-billing-lexical.json",
    "v2-billing-vector.json",
    "v2-billing-lexical-vector.json",
    "v2-billing-vector-adjacency.json",
    "v2-billing-lexical-vector-adjacency.json",
    "v2-sample-condition-ablation.json",
    "v2-billing-condition-ablation.json",
    # 两个 gates 产物：带统一指纹，但原先未登记，因此从未被本测试检查。
    # 实测它们与其余 13 份同指纹（47e4785-dirty / 36e9c16517）。
    "v2-sample-gates.json",
    "v2-billing-gates.json",
]

# 历史证据，不参与统一
HISTORICAL = [
    "v2-sample-lexical.json",
    "v2-sample-lexical-text.json",
]


def _load(name: str) -> dict[str, object]:
    path = RESULTS / name
    if not path.exists():
        pytest.skip(f"{name} 缺失")
    return json.loads(path.read_text(encoding="utf-8"))


def test_every_result_file_is_classified() -> None:
    """**v2-* 的每个 json 必须落在 CURRENT / HISTORICAL 之一。**

    为什么这条必须存在：上面两个清单是**显式文件名白名单**，不是 glob。
    所以任何新加的 `v2-*.json` 默认**不受任何指纹检查**。

    实测事故：有人把 `v3-authority-threshold-scan.json` 直接写进 `results/`，
    它没有 `code_version` / `code_diff_hash`，而所有测试都是绿的。

    **这是"检查存在，但范围小于它声称的范围"的第四次**：

    | # | 绕过方式 |
    |---|---|
    | L7 | 断言写"不是 uuid"，而传的是 tag |
    | F17 | 查"被任意轴指向"，本意是"被 A 轴指向" |
    | 无依据模块表 | 白名单只有两个条目 |
    | **本次** | **文件名不在显式清单里** |

    **为什么只约束 `v2-*` 而不约束全部**：`results/` 里还有 33 个 C4 时期的
    历史产物（`conflict-*`、`retrieval-*`、`a3-*`），它们不是 v2 评测，
    强行登记等于把"未受检查"合法化。所以这里的判据收窄为"**v2 前缀必须登记**"，
    而"整个 results/ 是否该分目录"是独立问题，见
    `test_results_contains_only_documented_prefixes`。
    """
    v2_on_disk = {p.name for p in RESULTS.glob("v2-*.json")}
    declared = set(CURRENT) | set(HISTORICAL)

    unclassified = v2_on_disk - declared
    assert not unclassified, (
        f"这些 v2-*.json 未登记，因此不受任何指纹检查：{sorted(unclassified)}\n"
        "把它们加进 CURRENT（需带统一指纹）或 HISTORICAL（需说明为何不统一）。"
    )

    missing = declared - v2_on_disk
    assert not missing, f"清单里登记但文件不存在：{sorted(missing)}"


def test_results_prefixes_are_documented() -> None:
    """`results/` 下的文件前缀必须在一个已知集合里。

    **这条记录的是它现在**没有**解决的问题**：`results/` 里混着 4 代产物
    （`conflict-*`、`retrieval-*`、`a3-*`、`v2-*`），只有 `v2-*` 受指纹检查。

    实测：33 个未登记文件中 26 个**没有 `code_version` / `code_diff_hash`**。
    它们大多是 C4 时期的产物，而 v2 报告引用的数字现在必须能追溯到
    `results/v2-*.json`——这一点仍是成立的，但"未登记即可绕过"是真实缺口。

    **本条只做一件事**：把前缀集合写死，让新增一个陌生前缀时有人被提醒，
    而不是静默通过。它不声称已解决分层问题。
    """
    KNOWN_PREFIXES = {"v2-", "conflict-", "retrieval-", "a3-", "c4-",
                      "equivalence-", "independent-", "full-context-",
                      "naive-rag-", "no-memory-", "p2b0-"}

    files = {p.name for p in RESULTS.glob("*.json")}
    unknown = {
        n for n in files if not any(n.startswith(pre) for pre in KNOWN_PREFIXES)
    }
    assert not unknown, (
        f"这些文件的前缀不在已知集合里：{sorted(unknown)}\n"
        "若它们是新的评测产物，请确认是否应受指纹检查后加入 KNOWN_PREFIXES；"
        "若是一次性探查，不该放进 results/。"
    )


def test_all_current_results_share_one_fingerprint() -> None:
    """**13 份当前结果必须同指纹**（11 份评测 + 2 份消融）。"""
    versions: set[str] = set()
    hashes: set[str] = set()

    for name in CURRENT:
        payload = _load(name)
        versions.add(str(payload.get("code_version")))
        hashes.add(str(payload.get("code_diff_hash")))

    assert len(versions) == 1, f"code_version 不统一：{versions}"
    assert len(hashes) == 1, f"code_diff_hash 不统一：{hashes}"
    assert None not in versions, "有文件没有 code_version"
    assert "None" not in hashes, "有文件没有 code_diff_hash"


def test_ablation_files_have_fingerprints() -> None:
    """消融文件必须有指纹与 `run_count`。

    这条测试此前会红——两份消融的 `code_version` 是 `None`。
    它是"补指纹"这个改动的验收标准。
    """
    for name in (
        "v2-sample-condition-ablation.json",
        "v2-billing-condition-ablation.json",
    ):
        payload = _load(name)
        assert payload.get("code_version"), f"{name} 缺 code_version"
        assert payload.get("code_diff_hash"), f"{name} 缺 code_diff_hash"
        assert payload.get("run_count"), f"{name} 缺 run_count"


def test_ablation_fingerprint_matches_result_files() -> None:
    """消融与评测必须用**同一个**指纹函数，所以值应当相同。

    两个工具各写各的指纹，就等于没有统一身份。
    """
    ablation = _load("v2-sample-condition-ablation.json")
    result = _load("v2-sample-threeway.json")

    assert ablation["code_version"] == result["code_version"]
    assert ablation["code_diff_hash"] == result["code_diff_hash"]


def test_historical_files_are_excluded_and_documented() -> None:
    """历史文件保留原指纹，且必须能从文件名看出是历史。

    `v2-sample-*` 是样例期产物。它们**不该**被重跑成新指纹，
    否则"补字段前后数字未变"就失去了对照物。
    """
    for name in HISTORICAL:
        payload = _load(name)
        assert payload.get("code_version") is not None
        # 不与当前版本相同
        current = _load("v2-sample-threeway.json")
        assert payload["code_version"] != current["code_version"], (
            f"{name} 被重跑成了当前版本，历史对照丢失"
        )


def test_supersedes_points_at_something_different() -> None:
    """`supersedes` 若存在，不得与当前指纹完全相同。

    完全相同的 `supersedes` 意味着"我覆盖了我自己"，没有信息量。
    """
    for name in CURRENT:
        payload = _load(name)
        old = payload.get("supersedes")
        if not isinstance(old, dict):
            continue
        same = (
            old.get("code_version") == payload.get("code_version")
            and old.get("code_diff_hash") == payload.get("code_diff_hash")
        )
        assert not same, f"{name} 的 supersedes 与当前完全相同"


def test_ablation_drop_values_are_stable() -> None:
    """补指纹不得改变任何数字。

    ledger  `drop = 0.6000`
    billing `drop = 0.7778`
    """
    led = _load("v2-sample-condition-ablation.json")
    bil = _load("v2-billing-condition-ablation.json")

    assert led["drop"] == pytest.approx(0.6, abs=1e-6)
    assert bil["drop"] == pytest.approx(0.7778, abs=1e-3)
