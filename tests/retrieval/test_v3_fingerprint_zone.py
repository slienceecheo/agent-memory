"""v2 与 v3 的指纹必须分区（tasks 3b.3 / 3b.4）。

**为什么必须分区，而不是共用一条断言**：v3 是 **BREAKING** 变更
（`RerankWeights` 去掉 `condition` 权重、`rerank()` 三项加权），
所以 v3 产物与 v2 的 15 份**必然不同指纹**。

若不分区：

- v3 文件进顶层 -> `test_result_shapes` 的"9 类 / 48"红
- v3 文件被并入统一指纹 -> `test_unified_fingerprint` 红

**两次红的原因都不是"指纹错了"，是"混进了不同版本的产物"**——
这正是 v2 早期"11 份结果混三次代码状态"的同一形态。

**空目录不等于通过**：`results/v3/` 现在不存在（或为空），
所以 3b.4 的断言此刻是空转。测试用 `pytest.skip` 显式声明这一点，
**不用"0 个文件全部满足"来假装通过**——那是 `paths_unwired = []` 的同型问题。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results"

# v2 冻结指纹。**版本号是完整字符串，差异哈希是完整 64 位**——
# 早先文档里的 `36e9c165` 是缩写前缀，不能直接与文件值比较。
V2_VERSION = "47e4785-dirty"
V2_DIFF_PREFIX = "36e9c165"


def _fingerprint(path: Path) -> tuple[str | None, str | None]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("code_version"), data.get("code_diff_hash")


def _v3_files(root: Path = RESULTS) -> list[Path]:
    """`root/v3/` 下的 json。**根目录是参数，不是模块常量**。

    这不是风格问题。若这里写死 `RESULTS`，主检查的 skip 条件就依赖
    **真实目录**而不是调用方给的目录——于是"传 tmp_path 时正常、
    生产路径上不跑"这种缺陷无法被测试抓到。
    """
    v3 = root / "v3"
    if not v3.exists():
        return []
    return sorted(v3.glob("*.json"))


def _is_v2_fingerprint(version: str | None, diff_hash: str | None) -> bool:
    """判断是否 v2 冻结指纹。

    **用前缀而不是完整值**：文档与结论里引用的是 `36e9c165`（8 位前缀），
    而文件里存 64 位。把 8 位前缀当完整值比较会永远红——
    而那会诱使人去改文档里的历史数字。
    """
    return version == V2_VERSION and bool(diff_hash) and str(diff_hash).startswith(
        V2_DIFF_PREFIX
    )


def test_v2_group_excludes_v3_files() -> None:
    """v2 的 15 份共享指纹不得包含 `results/v3/` 下的任何文件。

    **这条防的是"分区写成了并集"**：若指纹清单用 `rglob` 收集，
    v3 文件会被并进同一组，于是"15 份统一指纹"这个断言会因为
    多出一份而红——而红的原因不是指纹退化，是清单混了版本。
    """
    v3_names = {p.name for p in _v3_files()}

    from tests.retrieval.test_unified_fingerprint import CURRENT, HISTORICAL

    declared = set(CURRENT) | set(HISTORICAL)
    overlap = declared & v3_names

    assert not overlap, (
        f"v3 文件被登记进了 v2 的指纹清单：{sorted(overlap)}。"
        "v3 必须是独立的一组（不同装置 -> 不同指纹是预期，不是缺陷）。"
    )


def test_v2_group_fingerprint_is_frozen() -> None:
    """v2 的 15 份仍是 `47e4785-dirty / 36e9c165`（本变更不改 v2 档案）。

    这条的数值从**文件自身**读出后与常量比对，而不是只比常量——
    若某天有人重跑并覆盖了 v2 文件，这里会先红。
    """
    from tests.retrieval.test_unified_fingerprint import CURRENT

    observed = set()
    for name in CURRENT:
        path = RESULTS / name
        if not path.exists():
            pytest.skip(f"{name} 缺失")
        version, diff_hash = _fingerprint(path)
        assert _is_v2_fingerprint(version, diff_hash), (
            f"{name} 的指纹是 {(version, diff_hash)}，"
            f"应为 {V2_VERSION} / {V2_DIFF_PREFIX}…。v2 是冻结档案，本变更不应改动它。"
        )
        observed.add(version)

    # 全部 15 份还必须是**同一个**哈希，不只是同一个前缀。
    # 早先的教训：11 份结果混三次代码状态，前缀相同而完整值不同。
    hashes = {_fingerprint(RESULTS / name)[1] for name in CURRENT}
    assert len(hashes) == 1, (
        f"v2 当前批出现 {len(hashes)} 个不同差异哈希：{sorted(hashes)}。"
        "同批产物必须同源。"
    )
    assert observed == {V2_VERSION}


def _check_v3_files_are_distinct_from_v2(files: list[Path]) -> list[str]:
    """返回错误列表；空列表表示通过。**目录由调用方给，函数不读全局常量**。

    这样同一份逻辑能被两个来源驱动：

    | 调用方 | `files` 来自 | 验的是什么 |
    |---|---|---|
    | `test_v3_has_own_fingerprint` | 真实 `results/v3/` | 作品本身 |
    | `test_v3_fingerprint_check_actually_fires` | `tmp_path` | **检查本身会不会红** |

    **只有第二个存在时，第一个的 `skip` 才不是"永久 skip"**——
    否则"v3 目录为空"与"检查从不生效"在输出上完全一样。
    """
    errors: list[str] = []
    fingerprints = set()
    for path in files:
        version, diff_hash = _fingerprint(path)
        if version is None or diff_hash is None:
            errors.append(f"{path.name}: 缺指纹")
            continue
        fingerprints.add((version, diff_hash))

    if any(_is_v2_fingerprint(v, h) for v, h in fingerprints):
        errors.append(
            "出现了与 v2 相同的指纹；v3 是 BREAKING 变更，"
            "指纹相同说明这批结果是旧代码跑的"
        )
    return errors


def _run_v3_fingerprint_check(
    root: Path,
) -> tuple[str, list[str]]:
    """在主检查的位置上"调度"一次，返回 `(动作, 错误列表)`。

    `动作` 只有三种，模拟 pytest 的三种结果：

    | 动作 | 含义 |
    |---|---|
    | `"run"` | 有文件 -> 真的检查了 |
    | `"skip"` | 没文件 -> 空转（**只有这一种情况允许 skip**） |
    | `"fail"` | 有文件但检查不过 |

    **把调度抽成函数，是为了能断言"有文件时动作必然是 run"**：
    若 skip 条件写成"依赖真实目录是否存在"，那么在 `tmp_path` 上
    这个函数会返回 `"skip"` 而真实目录为空时也返回 `"skip"`——
    **两种完全不同的状态给出同一动作，断言就能区分它们。**
    """
    files = _v3_files(root)
    if not files:
        return "skip", []
    errors = _check_v3_files_are_distinct_from_v2(files)
    return ("fail", errors) if errors else ("run", [])


def test_v3_has_own_fingerprint() -> None:
    """v3 产物必须带指纹，且与 v2 的 15 份**不同**。

    **不同是预期**：`rerank.py` 是 BREAKING，代码版本/差异哈希必然变。
    这条要抓的是两种错误：

    | 错误 | 后果 |
    |---|---|
    | v3 文件没有指纹字段 | 无法说明它是哪个版本测的 |
    | v3 文件指纹等于 v2 的 | 说明它其实是 v2 代码跑的，被误标成 v3 |

    第二个错误尤其隐蔽：**文件名写着 v3，内容却是四特征排序**。
    """
    files = _v3_files()
    if not files:
        pytest.skip(
            "results/v3/ 尚不存在或为空：本条此刻是**空转**，不代表 v3 指纹已验证。"
            "但检查逻辑本身已由 `test_v3_fingerprint_check_actually_fires` "
            "在 tmp_path 上验证过会红——所以这个 skip 不是'永久 skip'。"
        )

    errors = _check_v3_files_are_distinct_from_v2(files)
    assert not errors, "\n".join(errors)


def test_nonempty_v3_never_skips(tmp_path: Path) -> None:
    """**有文件的分区，主检查 MUST NOT skip。**

    本条补的是 3b.5 的反方向：

    | 方向 | 断言 |
    |---|---|
    | 3b.5 | 每个文件 -> 必须被某个分区覆盖 |
    | **本条** | **分区有文件 -> 主检查必须真的跑** |

    **为什么需要它**：若 skip 条件写成"`results/v3/` 不存在就跳过"，
    那么当 v3 目录存在但主检查因为别的原因（路径错、条件写宽）
    仍然 skip 时，所有断言都是绿的——而 `s` 与 `pass` 在 CI 里
    看起来几乎一样。

    **实测三态**（用 `_run_v3_fingerprint_check`，与主检查同一份逻辑）：

    | 输入 | 应有动作 |
    |---|---|
    | 空目录 / 不存在 | `skip` |
    | 有合法文件 | `run` |
    | 有违规文件 | `fail` |
    """
    # 1) 目录不存在 -> 允许 skip
    empty_root = tmp_path / "empty"
    empty_root.mkdir()
    assert _run_v3_fingerprint_check(empty_root) == ("skip", [])

    # 2) 有合法文件 -> 必须 run，不许 skip
    good_root = tmp_path / "good"
    (good_root / "v3").mkdir(parents=True)
    (good_root / "v3" / "x.json").write_text(
        json.dumps(
            {
                "code_version": "9999999-dirty",
                "code_diff_hash": "a" * 64,
                "per_case": [],
            }
        ),
        encoding="utf-8",
    )
    action, errors = _run_v3_fingerprint_check(good_root)
    assert action == "run", (
        f"v3 目录有文件，动作却是 {action!r}——skip 条件写宽了。"
        "这正是'分区有产物但检查不跑'的形态。"
    )
    assert errors == []

    # 3) 有违规文件 -> 必须 fail（不是 skip、不是 run）
    bad_root = tmp_path / "bad"
    (bad_root / "v3").mkdir(parents=True)
    (bad_root / "v3" / "y.json").write_text(
        json.dumps({"per_case": []}), encoding="utf-8"
    )
    action, errors = _run_v3_fingerprint_check(bad_root)
    assert action == "fail", action
    assert errors and "缺指纹" in errors[0]


def test_v3_fingerprint_check_actually_fires(tmp_path: Path) -> None:
    """**用 tmp_path 证明检查会红**，不依赖 `results/v3/` 是否存在。

    这不是"造一个违例再删掉"，是**用临时目录做 fixture**：
    同一个 `_check_v3_files_are_distinct_from_v2`，喂三种输入，看它是否给出对应结果。

    | 输入 | 期望 |
    |---|---|
    | 带非 v2 指纹的文件 | 无错误 |
    | 无指纹的文件 | 报"缺指纹" |
    | 带 **v2** 指纹的文件 | 报"指纹相同" |

    没有这条，`results/v3/` 为空时上一条是 `skip`，
    而**"永久 skip"与"检查通过"在 CI 输出里几乎一样**——
    这正是 `paths_unwired = []`、`tie_count = 1` 的同型问题。
    """
    v3 = tmp_path / "v3"
    v3.mkdir()

    # 1) 合法：指纹存在且不是 v2 的
    good = v3 / "good.json"
    good.write_text(
        json.dumps(
            {
                "code_version": "9999999-dirty",
                "code_diff_hash": "a" * 64,
                "per_case": [],
            }
        ),
        encoding="utf-8",
    )
    assert _check_v3_files_are_distinct_from_v2([good]) == []

    # 2) 无指纹
    no_fp = v3 / "no-fp.json"
    no_fp.write_text(json.dumps({"per_case": []}), encoding="utf-8")
    errors = _check_v3_files_are_distinct_from_v2([no_fp])
    assert errors and "缺指纹" in errors[0], errors

    # 3) 带 v2 指纹（**这是最隐蔽的一种**：文件名写着 v3，内容却是旧代码跑的）
    fake_v2 = v3 / "looks-like-v3.json"
    fake_v2.write_text(
        json.dumps(
            {
                "code_version": V2_VERSION,
                "code_diff_hash": V2_DIFF_PREFIX + "0" * (64 - len(V2_DIFF_PREFIX)),
                "per_case": [],
            }
        ),
        encoding="utf-8",
    )
    errors = _check_v3_files_are_distinct_from_v2([fake_v2])
    assert errors and "v2 相同" in errors[0], errors


def test_v3_fingerprints_are_uniform_within_group() -> None:
    """**v3 组内部必须同指纹**——这一条在 v3 有多份产物时才生效。

    v2 的教训是"11 份结果混三次代码状态"。v3 若允许多次运行，
    同一批产物必须共享指纹，否则无法回答"这组数字是哪个版本测的"。
    """
    files = _v3_files()
    if len(files) < 2:
        pytest.skip("v3 产物少于 2 份：组内一致性此刻无对象可检")

    fingerprints = {_fingerprint(p) for p in files}
    assert len(fingerprints) == 1, (
        f"v3 组内出现 {len(fingerprints)} 种指纹：{sorted(fingerprints)}。"
        "同一批产物必须同源，否则数字不可归因。"
    )
