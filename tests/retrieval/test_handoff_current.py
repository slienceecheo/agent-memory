"""`docs/HANDOFF.md` 的状态必须与实际一致。

**为什么需要**：HANDOFF 曾滞后两轮，出现两处真矛盾：

| 位置 | 写的 | 实际 |
|---|---|---|
| 运行态 | `1001 passed` | 1172 |
| 协议状态 | "待冻结，尚未造数据" | 已冻结 + 2 个 subject |

而"待冻结"与"已冻结两次"并存是最容易被误读的——下一个人会以为还在造数据阶段。

**设计原则**：运行态数字只写在一处（§0），别处不重复。
这份文档 300+ 行，两处各写一份必然对不上。
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HANDOFF = ROOT / "docs" / "HANDOFF.md"


def _text() -> str:
    if not HANDOFF.exists():
        pytest.skip("HANDOFF 缺失")
    return HANDOFF.read_text(encoding="utf-8")


def test_current_state_is_section_zero() -> None:
    """"当前状态"必须在第 0 节——读者先看到状态，再看历史。"""
    text = _text()

    assert "## 0. 当前状态" in text
    # 位置在"项目是什么"之前
    assert text.index("## 0. 当前状态") < text.index("## 项目是什么")


def test_no_stale_test_counts() -> None:
    """不得出现旧的 pytest 计数。

    历史值：1001 / 1056 / 1098 / 1120 / 1149 / 1155 / 1165。
    当前值从 §0 读，别处不许重复。
    """
    text = _text()

    for stale in ("1001 passed", "1056 passed", "1098 passed"):
        assert stale not in text, f"HANDOFF 里还有旧计数 {stale!r}"


def test_protocol_is_marked_frozen_not_pending() -> None:
    """协议必须标为已冻结，不得再有"待冻结"。"""
    text = _text()

    assert "待冻结" not in text, "协议已冻结（两个 tag），不该再写待冻结"
    assert "已冻结" in text or "已冻结" in text


def test_gate_status_matches_actual_run() -> None:
    """§0 写的门禁三态必须与实际一致。

    **三态必须分开**：`applicable=False` 既不算通过也不算失败。
    旧写法只断言 `{label} {passed}/27`，那会把"不适用"隐藏掉。
    """
    text = _text()

    sys.path.insert(0, str(ROOT))
    from evals.datasets.retrieval_v2 import load_dataset
    from evals.tools.check_v2_dataset import run_all

    for name, label in (("sample", "ledger"), ("billing", "billing")):
        dataset_dir = ROOT / "data" / "retrieval-v2" / name
        if not dataset_dir.exists():
            pytest.skip(f"{name} 缺失")
        results = run_all(load_dataset(dataset_dir))
        passed = sum(1 for r in results if r.applicable and r.passed)
        na = sum(1 for r in results if not r.applicable)
        failed = sum(1 for r in results if r.applicable and not r.passed)

        # HANDOFF 里写的是 "ledger **19 通过 / 2 不适用 / 6 未通过**（共 27）"
        expected = f"{label} **{passed} 通过 / {na} 不适用 / {failed} 未通过**"
        assert expected in text, (
            f"HANDOFF 未写三态 `{expected}`。"
            "只写 `X/27` 会把'不适用'与'失败'压成一格。"
        )


def test_no_duplicate_runtime_block() -> None:
    """运行态计数只写一处。

    **判据是"含 `pytest -> ... passed` 这类计数行"，不是"含 pytest"。**
    历史上有两处各写一份完整运行态，结果对不上。

    正则必须支持带语言标记的围栏（` ```bash `），否则 ` ```bash ` 会与
    下一个 ` ``` ` 错配。而只认 `pytest` 会把 marker 说明里的
    `pytest -m locked_defect -q` 也当成计数块——那不是运行态。
    """
    text = _text()
    blocks = re.findall(r"```[a-z]*\n(.*?)```", text, re.S)
    counting = [
        b for b in blocks if re.search(r"^pytest\s+->\s+\d+ passed", b, re.M)
    ]

    assert len(counting) == 1, (
        f"有 {len(counting)} 处写了运行态计数，只应有一处"
    )


def test_every_failing_gate_is_classified() -> None:
    """§0 的未通过门禁表必须覆盖实际的未通过项。"""
    text = _text()

    sys.path.insert(0, str(ROOT))
    from evals.datasets.retrieval_v2 import load_dataset
    from evals.tools.check_v2_dataset import run_all

    failed: set[str] = set()
    for name in ("sample", "billing"):
        dataset_dir = ROOT / "data" / "retrieval-v2" / name
        if not dataset_dir.exists():
            continue
        failed |= {r.code for r in run_all(load_dataset(dataset_dir)) if not r.passed}

    # 样例上的 F19b/F20 依赖消融结果；F24 依赖结果文件——都已在结果目录里
    for code in failed:
        assert code in text, f"未通过项 {code} 没在 HANDOFF 里出现"


def test_locked_defect_count_matches_marker() -> None:
    """`locked_defect` 的标记数与收集数必须区分开写。

    **这两个数字不相等，而且原因具体**：
    `test_authority_and_status_have_no_variance_in_pool` 有 3 个 `parametrize` split，
    占 3 条测试但只算 1 个标记。

    **标记数必须用 AST 数装饰器，不能数字符串。**
    本文件里有一行 `"@pytest.mark"` 形态的字符串（就是这个测试在数标记），
    字符串法会把自己数进去，得到 20 而不是 19——**自指陷阱**。
    """
    import ast

    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-m", "locked_defect", "--collect-only", "-q"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    match = re.search(r"(\d+)/(\d+) tests? collected", result.stdout)
    if not match:
        pytest.skip("无法收集 locked_defect 测试")
    collected = int(match.group(1))

    # 用 AST 数真实装饰器，避免把本文件里的字符串算进去
    markers = 0
    for path in (ROOT / "tests").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(
                node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
            ):
                continue
            for dec in node.decorator_list:
                if "locked_defect" in ast.unparse(dec):
                    markers += 1

    text = _text()
    assert f"{markers} 个" in text, f"HANDOFF 未写标记数 {markers} 个"
    assert f"{collected} 条" in text, f"HANDOFF 未写收集数 {collected} 条"
    # 标记数必须小于收集数（有 parametrize 展开）
    assert markers < collected, f"标记 {markers} 不小于收集 {collected}，数据可疑"


def test_locked_defect_section_separates_observation_from_defect() -> None:
    """必须写明"观测结论不是缺陷"——否则清单会混入永远无法结案的条目。

    判据是"这个条目怎样才能变绿"：
      - 缺陷：改数据/改代码就能绿
      - 结论：没有"修好"这个状态
    """
    text = _text()

    assert "只有" in text and "可修复" in text
    assert "观测结论不是缺陷" in text
    assert "词面在 A 轴无增量" in text
    assert "怎样才能变绿" in text


def test_section_zero_answers_where_the_conclusions_are() -> None:
    """§0 必须能独立回答"结论在哪"——读者读完 §0 不该再去找。"""
    text = _text()
    section = text[: text.index("## 项目是什么")] if "## 项目是什么" in text else text

    assert "v2-what-it-measures.md" in section
    assert "四条" in section


def test_section_zero_lists_both_protocol_tags() -> None:
    """§0 必须写清哪个 tag 是当前有效版本。

    下一个人要复算必须知道协议版本；而两个 tag 并存会让人选错。
    """
    text = _text()
    section = text[: text.index("## 项目是什么")] if "## 项目是什么" in text else text

    assert "dataset-v2-protocol-r2" in section
    assert "cb9c77f" in section
    assert "当前有效" in section
    assert "e6a795a" in section


def test_section_zero_flags_billing_saturation_as_kept_failure() -> None:
    """§0 必须写明 `billing` 的 1.0000 是保留的失败，不是成绩。

    这是最容易被误读的数字——它看起来像满分。
    只写在后面的纪律节里，读 §0 的人不会知道。
    """
    text = _text()
    section = text[: text.index("## 项目是什么")] if "## 项目是什么" in text else text

    assert "1.0000" in section
    assert "实验设计失败" in section
    assert "不是成绩" in section


def test_next_steps_point_at_v3_not_more_v2_subjects() -> None:
    """下一步必须指向 v3，且明确说"不该铺第三个 subject"。"""
    text = _text()

    assert "v3" in text
    assert "不该" in text and "第三个" in text
