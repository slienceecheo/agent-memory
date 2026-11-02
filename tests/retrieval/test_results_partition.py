"""分区清单与磁盘两个方向的一致性（spec: 结果产物的分区）。

**这条 requirement 承诺了两个方向**，缺任一方向就等于只写了一半：

| 方向 | 违反形式 | 谁抓 |
|---|---|---|
| 清单覆盖磁盘 | 新增 `results/foo/` 未登记 | `test_zone_manifest_covers_known_directories` |
| **磁盘覆盖清单（反向）** | 登记了分区却从不创建 | **本文件** |
| `archive` 指纹规则 | 归档文件被并进当前批 | 本文件 |
| 空转的独立证明存在 | 有人删掉 `*_actually_fires` | 本文件 |

**为什么"反向"也要断言**：`ZONES` 里写了 `features`（预留但不存在）。
若放任这种登记，清单会慢慢变成"愿望清单"——登记一堆将来可能有的分区，
而每个都不存在，于是"清单覆盖磁盘"这条永远绿，且**没人知道哪些是真实的**。
所以规则是：**不存在的分区必须显式标为"预留"，其余必须存在**。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results"


def _is_not_yet_present(desc: str) -> bool:
    """分区是否被显式标为"现在不该有内容"。"""
    return any(
        marker in desc for marker in ("尚无产物", "预留", "尚不存在")
    )


def test_zones_marked_reserved_do_not_exist() -> None:
    """标为"预留/尚不存在"的分区**不得**已经存在——否则那条说明是假的。"""
    from tests.retrieval.test_results_zones import ZONES

    reserved = {z for z, desc in ZONES.items() if "预留" in desc or "尚不存在" in desc}
    for zone in reserved:
        path = RESULTS if zone == "." else RESULTS / zone
        assert not path.exists(), (
            f"分区 {zone!r} 在清单里写'预留/尚不存在'，但磁盘上它存在了。"
            "改清单的说明——不要留着过期的话。"
        )


def test_non_reserved_zones_exist() -> None:
    """**反向**：没标"尚无产物/预留"的分区必须真实存在。

    没有这条，`ZONES` 可以登记任意多个不存在的分区，
    而"清单覆盖磁盘"那条仍然全绿——**清单就成了愿望清单**。

    `v3` 被标为"**尚无产物**"而不是"预留"：它的位置与检查都已确定，
    只是本变更（装置变更）不产出数据。这两种状态要分开，否则
    "还没轮到"与"将来才有"会混成一件事。
    """
    from tests.retrieval.test_results_zones import ZONES

    missing = []
    for zone, desc in ZONES.items():
        if _is_not_yet_present(desc):
            continue
        path = RESULTS if zone == "." else RESULTS / zone
        if not path.exists():
            missing.append(zone)

    assert not missing, (
        f"这些分区没有标'尚无产物/预留'，但磁盘上不存在：{sorted(missing)}。"
        "要么建出它，要么在清单里写明它现在不该有内容。"
    )


def test_archive_fingerprint_rule() -> None:
    """`archive/` 的文件必须带指纹，且**不得**与当前批相同。

    spec 承诺："历史对照物不得并入当前批"。
    实测 `results/archive/v2-sample-threeway-cb9c77f.json` 的指纹是
    `8b1b600-dirty`，而当前批是 `47e4785-dirty`——**两个不同的代码状态**。

    这条抓的是：有人把归档文件当成"当前批的一部分"重新登记。
    那会让"当前批 15 份同源"这个断言失效，而**所有数字都不变**。
    """
    archive = RESULTS / "archive"
    if not archive.exists():
        pytest.skip("results/archive/ 不存在")

    from tests.retrieval.test_unified_fingerprint import CURRENT, HISTORICAL
    from tests.retrieval.test_v3_fingerprint_zone import (
        _is_v2_fingerprint,
    )

    files = sorted(archive.glob("*.json"))
    if not files:
        pytest.skip("results/archive/ 为空")

    missing = []
    same_as_current = []
    for path in files:
        data = json.loads(path.read_text(encoding="utf-8"))
        version = data.get("code_version")
        diff_hash = data.get("code_diff_hash")
        if version is None or diff_hash is None:
            missing.append(path.name)
            continue
        if _is_v2_fingerprint(version, diff_hash):
            same_as_current.append(path.name)

    assert not missing, f"这些归档文件缺指纹：{sorted(missing)}"
    assert not same_as_current, (
        f"这些归档文件的指纹与当前批相同：{sorted(same_as_current)}。"
        "归档与当前批必须是不同代码状态，否则'归档'这个分区没有意义。"
    )

    # 也不得被登记进当前批/历史批的指纹清单
    declared = set(CURRENT) | set(HISTORICAL)
    overlap = {p.name for p in files} & declared
    assert not overlap, f"归档文件被登记进指纹清单：{sorted(overlap)}"


def test_skip_has_an_independent_proof() -> None:
    """**"空转时有独立证明"这件事本身必须被断言**。

    spec 承诺：分区未就绪时，主校验跳过，且另有独立测试证明同一判据会失败。
    若那条独立测试被删掉，主校验的跳过就重新变成"永久跳过"——
    而两种状态在输出上完全一样（都是 `s`）。

    本条检查的就是"那个独立测试还存在着"。
    """
    zones_text = (ROOT / "tests" / "retrieval" / "test_results_zones.py").read_text(
        encoding="utf-8"
    )
    fp_text = (
        ROOT / "tests" / "retrieval" / "test_v3_fingerprint_zone.py"
    ).read_text(encoding="utf-8")

    assert "def test_zone_check_actually_fires(" in zones_text, (
        "分区检查的独立证明被删了。若它不在，主校验的 skip 就是永久 skip。"
    )
    assert "def test_v3_fingerprint_check_actually_fires(" in fp_text, (
        "指纹检查的独立证明被删了。"
    )
    # 两者都必须用 tmp_path，而不是依赖真实目录里恰好有违例文件
    assert "tmp_path" in zones_text
    assert "tmp_path" in fp_text
