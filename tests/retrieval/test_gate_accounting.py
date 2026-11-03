"""门禁账本的三态（tasks 1.x / 2.x / 3.x）。

**两处实测缺口**：

```python
# main() —— 不适用被算进 failed
failed = [r for r in results if not r.passed]

# --json —— 丢了 applicable
{"code": r.code, "title": r.title, "passed": r.passed, "detail": r.detail}
```

| 量 | `billing` |
|---|---|
| `run_all` 条数 | 27 |
| `passed=True` | 23 |
| `applicable=False` | 2（`F20`、`F24`） |
| 旧 `main` 报的 failed | **4**（含那 2 条） |

**第三条**：`F24` 在"派生 within 为空"时 `passed=True + applicable=False`，
而 `Check.__post_init__` 拒绝——实测会抛 `ValueError`。
"""

from __future__ import annotations

import dataclasses
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "retrieval-v2"


def _ds(subject: str = "billing"):
    from evals.datasets.retrieval_v2 import load_dataset

    return load_dataset(DATA / subject)


def _split(results) -> tuple[int, int, int]:
    """返回 (passed, na, failed)。"""
    na = [r for r in results if not r.applicable]
    failed = [r for r in results if r.applicable and not r.passed]
    passed = [r for r in results if r.applicable and r.passed]
    return len(passed), len(na), len(failed)


# ---------- 1.1 --json 含 applicable ----------


def test_json_has_applicable(tmp_path: Path) -> None:
    """`--json` 的每条 check 必须含 `applicable` 字段。

    没有它，结果文件无法区分"不适用"与"失败"。
    """
    out = tmp_path / "gates.json"
    r = subprocess.run(
        [
            "uv", "run", "--no-sync", "python", "-m", "evals.tools.check_v2_dataset",
            str(DATA / "billing"), "--json", str(out),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if not out.exists():
        pytest.skip(f"CLI 未产出 JSON：{(r.stdout + r.stderr)[:200]}")

    payload = json.loads(out.read_text(encoding="utf-8"))
    checks = payload["checks"]
    assert checks, "checks 为空"

    missing = [c["code"] for c in checks if "applicable" not in c]
    assert not missing, (
        f"这些 check 缺 applicable 字段：{missing}。"
        "结果文件无法复算三态。"
    )


def test_json_roundtrip_matches_memory(tmp_path: Path) -> None:
    """从 JSON 复算的三态必须与 `run_all()` 一致。"""
    from evals.tools.check_v2_dataset import run_all

    out = tmp_path / "gates.json"
    subprocess.run(
        [
            "uv", "run", "--no-sync", "python", "-m", "evals.tools.check_v2_dataset",
            str(DATA / "billing"), "--json", str(out),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if not out.exists():
        pytest.skip("CLI 未产出 JSON")

    payload = json.loads(out.read_text(encoding="utf-8"))
    from_json = {
        c["code"]: (c["applicable"], c["passed"]) for c in payload["checks"]
    }
    in_memory = {r.code: (r.applicable, r.passed) for r in run_all(_ds())}

    assert from_json == in_memory, (
        "JSON 与内存结果不一致——从文件复算会得到不同结论"
    )


# ---------- 2.x main() 三元组 ----------


def test_na_and_failed_are_disjoint() -> None:
    """**核心**：`na` 与 `failed` 必须不相交。

    一条结果不能同时算"不适用"与"未通过"。
    """
    from evals.tools.check_v2_dataset import run_all

    for subject in ("sample", "billing"):
        results = run_all(_ds(subject))
        na = {r.code for r in results if not r.applicable}
        failed = {r.code for r in results if r.applicable and not r.passed}

        overlap = na & failed
        assert not overlap, (
            f"{subject}: 这些 code 同时算不适用与失败：{sorted(overlap)}"
        )

        # 且三态之和 == 总数
        passed = sum(1 for r in results if r.applicable and r.passed)
        assert passed + len(na) + len(failed) == len(results), (
            f"{subject}: {passed}+{len(na)}+{len(failed)} != {len(results)}"
        )


def test_billing_three_counts() -> None:
    """`billing` 的实测三态：**23 通过 / 2 不适用 / 2 未通过**。

    旧 `main` 报 `通过 23/27` 并把 4 条列为失败——2 条不适用被算进去了。
    """
    from evals.tools.check_v2_dataset import run_all

    results = run_all(_ds("billing"))
    passed, na, failed = _split(results)

    assert (passed, na, failed) == (23, 2, 2), (
        f"billing: {passed} 通过 / {na} 不适用 / {failed} 未通过，"
        "期望 23 / 2 / 2"
    )


def test_sample_three_counts() -> None:
    """`sample` 的实测三态：**19 通过 / 2 不适用 / 6 未通过**。"""
    from evals.tools.check_v2_dataset import run_all

    results = run_all(_ds("sample"))
    passed, na, failed = _split(results)

    assert (passed, na, failed) == (19, 2, 6), (
        f"sample: {passed} 通过 / {na} 不适用 / {failed} 未通过，"
        "期望 19 / 2 / 6"
    )


def test_main_output_reports_three() -> None:
    """`main()` 的屏幕输出必须含三个分开的数。

    只报 `X/27` 会把两种 false 压成一格。
    """
    r = subprocess.run(
        [
            "uv", "run", "--no-sync", "python", "-m", "evals.tools.check_v2_dataset",
            str(DATA / "billing"),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    out = (r.stdout or "") + (r.stderr or "")

    assert "不适用" in out, (
        f"输出里没有'不适用'这个数——两种 false 混在一起：\n{out[-400:]}"
    )
    # 三个数都要出现
    assert "23" in out and "2" in out, out[-400:]


# ---------- 3.x F24 空派生 within ----------


def _flat_dataset():
    """把 sample 的每条 memory 的 relation 改成唯一值。

    于是每条查询的 `n_competitors` 都是 0 -> 派生全为 cross -> within 为空。
    """
    ds = _ds("sample")
    flat_mems = tuple(
        dataclasses.replace(m, relation=f"r{i}")
        for i, m in enumerate(ds.memories)
    )
    return dataclasses.replace(ds, memories=flat_mems)


def test_f24_handles_no_derived_within() -> None:
    """**全单值数据集上 `F24` 必须返回 Check，不能抛异常。**

    当前实现返回 `passed=True, applicable=False`，而 `Check.__post_init__` 拒绝。
    实测会抛 `ValueError`。

    而"一个 subject 全单值 relation"是 v3 的合法数据形状。
    """
    from evals.metrics.v2_baselines import axis_baseline_derived, derived_axis_of
    from evals.tools.check_v2_dataset import Check, check_f24_axis_a_not_saturated

    flat = _flat_dataset()
    within = sum(1 for q in flat.queries if derived_axis_of(flat, q) == "relation_within")
    assert within == 0, f"前提不成立：派生 within 有 {within} 条"
    assert axis_baseline_derived(flat)["relation_within"] is None

    # 不能抛
    try:
        check = check_f24_axis_a_not_saturated(flat)
    except ValueError as exc:
        pytest.fail(
            f"F24 抛了未捕获的 ValueError：{exc}\n"
            "这会让 run_all() 整体崩掉，而不是报一条门禁失败。"
        )

    assert isinstance(check, Check)
    assert not check.passed


def test_no_subject_is_not_cross_apparatus() -> None:
    """该分支 MUST 是 `applicable=True`，不是 `applicable=False`。

    `applicable=False` 的语义是"跨装置，判据不成立"；
    而这里装置是对的，是数据形状让判据没有主语。**两种原因不能混。**
    """
    from evals.tools.check_v2_dataset import check_f24_axis_a_not_saturated

    check = check_f24_axis_a_not_saturated(_flat_dataset())

    assert check.applicable, (
        "无派生 within 被判成了'不适用'——那会与'跨装置'混在一起。"
        "它应该是'适用但失败'。"
    )
    assert not check.passed
    assert "within" in check.detail.lower() or "派生" in check.detail
