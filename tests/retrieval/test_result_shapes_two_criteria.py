"""两套独立判据验证结果文件的九类分类。

**为什么需要两套**：`test_result_shapes.py` 的判据和 HANDOFF 的表格
是按同一个逻辑写的。若那个逻辑有一处判错，文档和测试会**一起错**，
而彼此一致——所以测试通过。

这与这一路反复出现的形态相同：**测试和文档共享同一个错误来源，
于是测试证明不了文档。**

所以本文件用**不同的判据**重算一遍：

| | 判据 A（test_result_shapes） | 判据 B（本文件） |
|---|---|---|
| 优先级 | 先 list，再 dict，再账本，最后分节 | **先账本**，再 list，再条件消融，再分节 |
| 账本识别 | 键以 `.json` 结尾 + 值全 int | **只看值全 int**，不看键名 |
| 分节报告 | 兜底 `any(isinstance(v, (dict, list)))` | **要求 `variants` 键为三 split** |

两套判据**结构不同**（优先级顺序不同、账本判据不同、分节报告判据不同），
所以它们同时得到同一分类，才说明分类不依赖于某一个判据的写法。

**这正是用户提出的判据**：

> 任何"分类必须穷尽"的测试，应该有两套独立判据，
> 断言 A 与 B 得到同一分类。
> 而不是"文档写 X，测试断言 X"——那只防手误，不防分类逻辑本身错。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results"

LIST_KEYS = ("per_case", "samples", "checks", "rows", "cases")


def classify_a(path: Path) -> str:
    """判据 A（与 test_result_shapes.py 相同）：list 字段名优先。"""
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return "BAD_JSON"
    if isinstance(d, list):
        return "top_list"
    if not isinstance(d, dict):
        return "BAD_JSON"

    for key in LIST_KEYS:
        if isinstance(d.get(key), list):
            return key
    if isinstance(d.get("with_condition"), dict) or isinstance(
        d.get("without_condition"), dict
    ):
        return "dict_case_id"
    if (
        d
        and all(isinstance(v, int) for v in d.values())
        and all(str(k).endswith(".json") for k in d)
    ):
        return "ledger"
    if d and any(isinstance(v, (dict, list)) for v in d.values()):
        return "sectioned_report"
    return "UNCLASSIFIED"


def classify_b(path: Path) -> str:
    """判据 B：**账本优先**，不依赖键名；分节报告要求 variants 键已知。

    结构与 A 不同：
      1. 先判"值全为 int"（账本），不看键是否以 .json 结尾
      2. 再判顶层 list
      3. 再判五类 list 字段名
      4. 再判 with_condition / without_condition
      5. 最后才判分节报告，且要求 variants 的键恰为 {dev,test,independent}
    """
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return "BAD_JSON"

    # 1. 账本：非空 dict 且所有值都是 int
    if isinstance(d, dict) and d and all(isinstance(v, int) for v in d.values()):
        return "ledger"

    # 2. 顶层 list
    if isinstance(d, list):
        return "top_list"
    if not isinstance(d, dict):
        return "BAD_JSON"

    # 3. 五类 list 字段名（反序扫描，验证顺序不影响结果）
    for key in reversed(LIST_KEYS):
        if isinstance(d.get(key), list):
            return key

    # 4. 条件消融的嵌套 dict
    if (
        "with_condition" in d
        and "without_condition" in d
        and all(isinstance(d[k], dict) for k in ("with_condition", "without_condition"))
    ):
        return "dict_case_id"

    # 5. 分节报告：要求 variants 存在且键恰为三个 split
    variants = d.get("variants")
    if isinstance(variants, dict) and set(variants) == {"dev", "test", "independent"}:
        return "sectioned_report"

    return "UNCLASSIFIED"


def test_both_criteria_agree_on_every_file() -> None:
    """**两套判据必须对每个文件给同一分类。**

    这是本文件的核心断言。它们不一致时，说明分类依赖于判据写法，
    而不是文件本身的性质。
    """
    files = sorted(p for p in RESULTS.glob("*.json") if p.parent == RESULTS)
    assert len(files) == 48, f"文件数变成 {len(files)}"

    disagreements = [
        (p.name, classify_a(p), classify_b(p))
        for p in files
        if classify_a(p) != classify_b(p)
    ]

    assert not disagreements, (
        "两套判据给出不同分类：\n"
        + "\n".join(f"  {n}: A={a}, B={b}" for n, a, b in disagreements)
    )


def test_both_criteria_sum_to_48() -> None:
    """两套判据的加总都必须等于文件数。"""
    files = sorted(p for p in RESULTS.glob("*.json") if p.parent == RESULTS)

    for name, fn in (("A", classify_a), ("B", classify_b)):
        counts: dict[str, int] = {}
        for p in files:
            k = fn(p)
            counts[k] = counts.get(k, 0) + 1
        assert sum(counts.values()) == len(files), (
            f"判据 {name} 加总 {sum(counts.values())} != {len(files)}"
        )
        assert "UNCLASSIFIED" not in counts, (
            f"判据 {name} 有未归类文件：{counts.get('UNCLASSIFIED')}"
        )


def test_both_criteria_are_structurally_different() -> None:
    """两套判据必须**结构不同**，否则"独立验证"是假的。

    构造一个只有判据 B 认得的样例：键不以 `.json` 结尾但值全为 int。
    A 判为非账本（进入后面的分支），B 判为账本。
    """
    probe = {"alpha": 1, "beta": 2}
    tmp = RESULTS / "_probe_ledger.json"
    try:
        tmp.write_text(json.dumps(probe), encoding="utf-8")
        a = classify_a(tmp)
        b = classify_b(tmp)
        assert a != b, (
            f"两套判据在这个样例上给出了同一答案 {a}，"
            "说明它们没有结构差异，独立验证不成立"
        )
        assert b == "ledger", f"B 应判为账本，实际 {b}"
    finally:
        tmp.unlink(missing_ok=True)


def test_criteria_never_diverge_on_real_files() -> None:
    """**如实记录**：在真实的 48 个文件上，两套判据从不分歧。

    这意味着"独立验证"的价值有限：

    | 能证明什么 | 不能证明什么 |
    |---|---|
    | 分类不依赖某一个判据的**写法** | 分类**逻辑本身**是否正确 |

    因为两套判据虽然路径不同，但**对 48 个文件的判定结果完全一致**——
    若分类逻辑本身有一处共同错误（例如"该有几类"这个前提错了），
    两套判据会一起错，正如文档与单套测试会一起错。

    **真正独立于"分类逻辑"的验证只有一种**：拿一个第三方（人或另一个模型）
    不看本文档、自己数一遍。而那不是测试能做的。
    """
    files = sorted(p for p in RESULTS.glob("*.json") if p.parent == RESULTS)
    diverged = [p.name for p in files if classify_a(p) != classify_b(p)]

    assert not diverged, (
        f"真实文件上出现分歧（这反而是好事，说明判据有区分力）：{diverged}"
    )


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("v2-sample-gates.json", "checks"),
        ("p2b0-judge-probe.json", "cases"),
        ("equivalence-classification.json", "rows"),
        ("independent-variants.json", "top_list"),
        ("retrieval-run-count.json", "ledger"),
        ("v2-sample-condition-ablation.json", "dict_case_id"),
        ("c4-query-leak-ablation.json", "sectioned_report"),
    ],
)
def test_both_criteria_on_representative_files(name: str, expected: str) -> None:
    """每类代表文件在两套判据下都必须归入同一类。"""
    path = RESULTS / name
    if not path.exists():
        pytest.skip(f"{name} 缺失")
    assert classify_a(path) == expected, f"A 判据把 {name} 判成了 {classify_a(path)}"
    assert classify_b(path) == expected, f"B 判据把 {name} 判成了 {classify_b(path)}"
