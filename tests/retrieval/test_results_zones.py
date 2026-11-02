"""`results/` 的分区穷尽性（tasks 3b.2b / 3b.5）。

**这两条防的是同一个问题的两个方向**：

1. `rglob` 扫到了子目录，但没有任何检查处理它 —— 新的"子目录不检查"
2. 分区清单漏了一项（例如 `results/features/`），而它出现时才红 ——
   那时人会以为"发现了新盲区"，实际是"清单少写一行"

所以判据必须是**先枚举清单，再验穷尽**，且清单里写明"预留但尚未覆盖"。

**为什么现在就必须写，而不是等 v3 目录出现再写**：
`results/archive/` 已经存在（1 个 json），而当前没有任何检查约束它。
这就是"子目录不检查"的现成实例——只是它历史足够久，没人再问。
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results"

# 分区清单。键是相对 `results/` 的 posix 路径（顶层为 "."），
# 值是"该分区由谁检查"。
#
# **三种状态必须分开写，不能含糊**：
#
# | 措辞 | 含义 |
# |---|---|
# | 正常的检查说明 | 分区存在，且有检查在跑 |
# | "**尚无产物**" | 分区**应该存在**，但本变更不产出内容（目录可能还没建） |
# | "**预留，尚不存在**" | 分区是将来才有的，现在连内容形态都没定 |
#
# 三者混同的后果：`ZONES` 会变成愿望清单——登记一堆不存在的分区，
# 而"清单覆盖磁盘"那条仍然全绿。`test_results_partition.py` 会抓这一点。
ZONES: dict[str, str] = {
    ".": "v2 档案：test_result_shapes（9 类 / 48）+ test_unified_fingerprint（15 份共享指纹）",
    "v3": "v3 评测产物：**尚无产物**（本变更是装置变更，不产数据）；"
    "校验在 test_v3_fingerprint_zone（独立指纹，不得等于 v2）",
    "archive": "历史对照物：有指纹，且**不得并入当前批**"
    "（实测 8b1b600-dirty vs 当前批 47e4785-dirty）",
    "features": "**预留，尚不存在**：逐条特征分（若独立成文件）",
}


def _zone_of(path: Path, root: Path = RESULTS) -> str:
    return "." if path.parent == root else path.parent.relative_to(root).as_posix()


def _unclassified(
    files: list[Path], *, root: Path, zones: dict[str, str] = ZONES
) -> list[str]:
    """返回未登记分区的文件。**根目录与清单都由调用方给**，不读全局常量。

    这样同一份逻辑能被真实目录与 `tmp_path` 两个来源驱动：
    前者验"作品本身"，后者验"检查会不会红"。
    """
    out: list[str] = []
    for path in files:
        zone = _zone_of(path, root)
        if zone not in zones:
            out.append(f"{path.relative_to(root).as_posix()} -> 分区 {zone!r}")
    return out


def test_every_result_file_is_classified() -> None:
    """任何 `results/**/*.json` 都必须落在已登记分区里。

    **用 `rglob` 而不是 `glob`**：这条的意图是"所有结果文件都被登记"，
    所以它必须能看到子目录。若用 `glob`，`results/archive/` 与
    `results/v3/` 会永远不被看见——**而"看不见"与"通过"在输出上一样。**
    """
    unclassified = _unclassified(list(RESULTS.rglob("*.json")), root=RESULTS)

    assert not unclassified, (
        "这些文件位于未登记的分区，因而不受任何检查：\n"
        + "\n".join(f"  {u}" for u in sorted(unclassified))
        + f"\n已登记分区：{sorted(ZONES)}"
    )


def test_zone_check_actually_fires(tmp_path: Path) -> None:
    """**用 tmp_path 证明分区检查会红**，不依赖真实目录里恰好有违例文件。

    三种输入，三种结果：

    | 输入 | 期望 |
    |---|---|
    | `tmp/v3/x.json` | 通过（v3 已登记） |
    | `tmp/archive/x.json` | 通过（archive 已登记） |
    | `tmp/unknown/x.json` | 报"未登记分区" |

    没有这条，`test_every_result_file_is_classified` 只在"有人真的放错文件"
    时才验到东西——**而"没人放错"与"检查不生效"在输出上一样。**
    """
    root = tmp_path / "results"
    for zone in ("v3", "archive", "unknown"):
        (root / zone).mkdir(parents=True)
        (root / zone / "x.json").write_text("{}", encoding="utf-8")

    files = list(root.rglob("*.json"))

    unclassified = _unclassified(files, root=root)
    assert len(unclassified) == 1, unclassified
    assert "unknown" in unclassified[0]
    assert "未登记" in unclassified[0] or "分区" in unclassified[0]

    # 登记 unknown 后应全绿——证明这条不是因为"文件数不等于 3"之类的原因而红
    widened = {**ZONES, "unknown": "临时分区"}
    assert _unclassified(files, root=root, zones=widened) == []


def test_nonempty_zone_never_skips(tmp_path: Path) -> None:
    """**有文件的分区，分区检查 MUST NOT skip。**

    与 `test_nonempty_v3_never_skips` 同型，补的是"分区有文件但检查不跑"。

    `test_every_result_file_is_classified` 本身不 skip（它扫真实目录），
    但它依赖 `_unclassified(files, root=...)` 的 `root` 参数正确。
    若某处把 `root` 写死，传 `tmp_path` 时仍会"正常"，而生产路径上不跑——
    **那正是"条件写宽"的形态。**

    三态：

    | 输入 | 应有结果 |
    |---|---|
    | 只有已登记分区 | `[]` |
    | 含未登记分区 | 非空且指出分区名 |
    | 空目录 | `[]`（此时确实没有对象可检，但**不 skip**） |
    """
    # 1) 已登记
    good = tmp_path / "good"
    for zone in ("v3", "archive"):
        (good / zone).mkdir(parents=True)
        (good / zone / "x.json").write_text("{}", encoding="utf-8")
    assert _unclassified(list(good.rglob("*.json")), root=good) == []

    # 2) 未登记
    bad = tmp_path / "bad"
    (bad / "unknown").mkdir(parents=True)
    (bad / "unknown" / "x.json").write_text("{}", encoding="utf-8")
    errors = _unclassified(list(bad.rglob("*.json")), root=bad)
    assert errors and "unknown" in errors[0]

    # 3) 空目录 -> 无错误，且**不是因为 skip**
    empty = tmp_path / "empty"
    empty.mkdir()
    assert _unclassified(list(empty.rglob("*.json")), root=empty) == []


def test_zone_manifest_covers_known_directories() -> None:
    """磁盘上存在的子目录必须在清单里——防"清单漏一项"。

    与上一条的区别：上一条只在**该目录里有 json** 时才红；
    这一条在**目录存在但为空**时也红。两者覆盖不同的时刻。
    """
    on_disk = {
        d.relative_to(RESULTS).as_posix()
        for d in RESULTS.iterdir()
        if d.is_dir()
    }
    missing = on_disk - set(ZONES) - {"."}

    assert not missing, (
        f"这些子目录存在但不在分区清单里：{sorted(missing)}\n"
        "在 ZONES 里登记它，并写明由谁检查。"
    )


def test_top_level_count_is_frozen_at_48() -> None:
    """`results/*.json` 顶层永远是 48 个（v2 档案，冻结）。

    **这条与"递归总数"是两个量**：递归数现在包含 `results/archive/` 的 1 个文件。
    若把两者混用，v3 每加一个文件都要改 `48`，而 `48` 是 v2 的历史事实。
    """
    top_level = [p for p in RESULTS.glob("*.json") if p.parent == RESULTS]
    recursive = list(RESULTS.rglob("*.json"))

    assert len(top_level) == 48, (
        f"顶层 {len(top_level)} 个 json，应为 48（v2 档案）。"
        "v3 产物请写 results/v3/，不要进顶层。"
    )
    assert len(recursive) >= len(top_level), "递归数不可能小于顶层数"


def test_archive_zone_has_no_fingerprint_claim() -> None:
    """**登记 `archive/` 不等于验证它。**

    这条把"未检查"写成可执行的断言：`archive/` 里的文件不参与指纹检查。
    若将来把它纳入，这条会红——那时应该删掉它并加上真正的检查，
    而不是让它静默变成"已检查"。
    """
    archive = RESULTS / "archive"
    if not archive.exists():
        pytest.skip("results/archive/ 不存在")

    # 这是一个"事实记录"断言：archive 当前不在指纹白名单里。
    from tests.retrieval.test_unified_fingerprint import CURRENT, HISTORICAL

    archive_names = {p.name for p in archive.glob("*.json")}
    declared = set(CURRENT) | set(HISTORICAL)
    overlap = archive_names & declared

    assert not overlap, (
        f"archive/ 里的文件被登记进了指纹白名单：{sorted(overlap)}。"
        "若确实要验证它们，请先确认它们的指纹口径，再更新本测试的说明。"
    )
