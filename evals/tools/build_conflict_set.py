"""生成冲突场景集（60 条：dev 40 + test 20）。

**重要：这里生成的标签是机器提议的（`label_status = "proposed"`）。**

场景的文本由人设计、覆盖真实表达；但期望标签必须经人工确认后才作为验收依据。
理由见 design.md D6：用规则生成的标签去测规则是循环论证。

运行：
    uv run python -m evals.tools.build_conflict_set
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "data" / "conflict-set"

# (id, text, subject, relation, candidate_value, existing_value, expected,
#  condition, existing_condition, authority, note)
Case = tuple[
    str, str, str, str, str, str | None, str, str | None, str | None, str, str
]

_PM = "package_manager"
_PROJ = "project:agent-memory"

DEV: list[Case] = [
    # ---- NOOP（重复陈述）7 条 ----
    ("dev-noop-01", "我们用 pnpm", _PROJ, _PM, "pnpm", "pnpm", "NOOP", None, None, "user_direct", "完全重复"),
    ("dev-noop-02", "这个仓库的包管理器是 pnpm", _PROJ, _PM, "pnpm", "pnpm", "NOOP", None, None, "user_direct", "换句说法但内容相同"),
    ("dev-noop-03", "测试只跑 pytest", _PROJ, "test_command", "pytest", "pytest", "NOOP", None, None, "user_direct", "重复确认"),
    ("dev-noop-04", "默认分支是 main", _PROJ, "default_branch", "main", "main", "NOOP", None, None, "user_direct", "重复确认"),
    ("dev-noop-05", "我们统一用 ruff 做格式化", _PROJ, "code_style", "ruff", "ruff", "NOOP", None, None, "user_direct", "重复确认"),
    ("dev-noop-06", "值班人是张三", _PROJ, "oncall_owner", "张三", "张三", "NOOP", None, None, "user_direct", "重复确认"),
    ("dev-noop-07", "   我们用 pnpm   ", _PROJ, _PM, "pnpm", "pnpm", "NOOP", None, None, "user_direct", "多余空白"),

    # ---- ADD（全新事实）7 条 ----
    ("dev-add-01", "我们用 pnpm 管理依赖", _PROJ, _PM, "pnpm", None, "ADD", None, None, "user_direct", "首次建立"),
    ("dev-add-02", "部署目标是 k8s", _PROJ, "deploy_target", "k8s", None, "ADD", None, None, "user_direct", "首次建立"),
    ("dev-add-03", "评审人是李四", _PROJ, "reviewer", "李四", None, "ADD", None, None, "user_direct", "首次建立"),
    ("dev-add-04", "代码风格用 black", "project:other", "code_style", "black", None, "ADD", None, None, "user_direct", "另一个项目，首次建立"),
    ("dev-add-05", "测试命令是 npm test", "project:other", "test_command", "npm test", None, "ADD", None, None, "user_direct", "首次建立"),
    ("dev-add-06", "开会时间定在周一上午", _PROJ, "meeting_time", "周一上午", None, "ADD", "weekly", None, "user_direct", "带条件的首次建立"),
    ("dev-add-07", "写代码时间我喜欢深夜", _PROJ, "coding_time", "深夜", None, "ADD", "coding", None, "user_direct", "带条件的首次建立"),

    # ---- MERGE（补充，旧值仍成立）7 条 ----
    ("dev-merge-01", "我们用 pnpm，另外还用了 workspace", _PROJ, _PM, "pnpm 加 workspace", "pnpm", "MERGE", None, None, "user_direct", "补充细节"),
    ("dev-merge-02", "测试跑 pytest，覆盖率要求 80%", _PROJ, "test_command", "pytest 覆盖率要求 80%", "pytest", "MERGE", None, None, "user_direct", "补充细节"),
    ("dev-merge-03", "部署到 k8s，用 helm 管理", _PROJ, "deploy_target", "k8s 用 helm", "k8s", "MERGE", None, None, "user_direct", "补充细节"),
    ("dev-merge-04", "默认分支 main，要求保护分支", _PROJ, "default_branch", "main 保护分支", "main", "MERGE", None, None, "user_direct", "补充细节"),
    ("dev-merge-05", "用 ruff，配置在 pyproject.toml 里", _PROJ, "code_style", "ruff 配置在 pyproject", "ruff", "MERGE", None, None, "user_direct", "补充细节"),
    ("dev-merge-06", "值班人张三，周三不在", _PROJ, "oncall_owner", "张三 周三不在", "张三", "MERGE", None, None, "user_direct", "补充细节"),
    ("dev-merge-07", "评审人李四，同时需要王五 approve", _PROJ, "reviewer", "李四 王五", "李四", "MERGE", None, None, "user_direct", "补充细节"),

    # ---- SUPERSEDE（取代）7 条 ----
    ("dev-sup-01", "我们这个仓库现在改用 npm 了", _PROJ, _PM, "npm", "pnpm", "SUPERSEDE", None, None, "user_direct", "明确改主意"),
    ("dev-sup-02", "测试命令改成 npm test 了", _PROJ, "test_command", "npm test", "pytest", "SUPERSEDE", None, None, "user_direct", "明确改主意"),
    ("dev-sup-03", "部署目标换成 bare metal", _PROJ, "deploy_target", "bare metal", "k8s", "SUPERSEDE", None, None, "user_direct", "明确改主意"),
    ("dev-sup-04", "默认分支不再是 main，改成 trunk", _PROJ, "default_branch", "trunk", "main", "SUPERSEDE", None, None, "user_direct", "明确改主意"),
    ("dev-sup-05", "不再用 ruff，改成 flake8", _PROJ, "code_style", "flake8", "ruff", "SUPERSEDE", None, None, "user_direct", "明确改主意"),
    ("dev-sup-06", "值班人换成了王五", _PROJ, "oncall_owner", "王五", "张三", "SUPERSEDE", None, None, "user_direct", "明确改主意"),
    ("dev-sup-07", "评审人从李四改成赵六", _PROJ, "reviewer", "赵六", "李四", "SUPERSEDE", None, None, "user_direct", "明确改主意"),

    # ---- BRANCH（条件不同）6 条 ----
    ("dev-branch-01", "写代码的时候我喜欢深夜", _PROJ, "meeting_time", "深夜", "早上", "BRANCH", "coding", "meeting", "user_direct", "同一关系不同场景"),
    ("dev-branch-02", "开会时我喜欢早上", _PROJ, "coding_time", "早上", "深夜", "BRANCH", "meeting", "coding", "user_direct", "同一关系不同场景"),
    ("dev-branch-03", "线上环境优先稳定性", _PROJ, "deploy_target", "稳定性优先", "快速迭代", "BRANCH", "prod", "dev", "user_direct", "环境不同"),
    ("dev-branch-04", "本地开发用 sqlite", _PROJ, "test_command", "sqlite", "postgres", "BRANCH", "local", "prod", "user_direct", "环境不同"),
    ("dev-branch-05", "小项目用 ruff 就够了", "project:other", "code_style", "ruff", "mypy strict", "BRANCH", "small", "large", "user_direct", "规模不同"),
    ("dev-branch-06", "前端目录用 prettier", _PROJ, "code_style", "prettier", "ruff", "BRANCH", "frontend", "backend", "user_direct", "目录不同"),

    # ---- CONFLICT（权威不足或无法裁决）6 条 ----
    ("dev-conf-01", "客户吃花生会过敏", "user:alice", "dietary_restriction", "对花生过敏", "能吃花生", "CONFLICT", None, None, "third_party", "工单备注 vs 用户自述"),
    ("dev-conf-02", "工单里说客户能吃海鲜", "user:alice", "dietary_restriction", "能吃海鲜", "不能吃海鲜", "CONFLICT", None, None, "third_party", "工单备注 vs 用户自述"),
    ("dev-conf-03", "用的应该是 yarn 吧", _PROJ, _PM, "yarn", "pnpm", "CONFLICT", None, None, "system_inferred", "系统推断 vs 用户自述"),
    ("dev-conf-04", "有人说测试命令是 jest", _PROJ, "test_command", "jest", "pytest", "CONFLICT", None, None, "third_party", "他人转述"),
    ("dev-conf-05", "可能部署在阿里云", _PROJ, "deploy_target", "阿里云", "AWS", "CONFLICT", None, None, "system_inferred", "不确定的推断"),
    ("dev-conf-06", "外部审计说默认分支是 develop", _PROJ, "default_branch", "develop", "main", "CONFLICT", None, None, "third_party", "外部来源"),
]

TEST: list[Case] = [
    # NOOP 3
    ("test-noop-01", "我们就用 pnpm", _PROJ, _PM, "pnpm", "pnpm", "NOOP", None, None, "user_direct", ""),
    ("test-noop-02", "测试跑 pytest", _PROJ, "test_command", "pytest", "pytest", "NOOP", None, None, "user_direct", ""),
    ("test-noop-03", "默认分支 main", _PROJ, "default_branch", "main", "main", "NOOP", None, None, "user_direct", ""),
    # ADD 3
    ("test-add-01", "我们用 bun 作为运行时", "project:new", _PM, "bun", None, "ADD", None, None, "user_direct", ""),
    ("test-add-02", "部署目标是 fly.io", "project:new", "deploy_target", "fly.io", None, "ADD", None, None, "user_direct", ""),
    ("test-add-03", "评审人是钱七", "project:new", "reviewer", "钱七", None, "ADD", None, None, "user_direct", ""),
    # MERGE 3
    ("test-merge-01", "用 bun，同时锁定了版本", "project:new", _PM, "bun 锁定版本", "bun", "MERGE", None, None, "user_direct", ""),
    ("test-merge-02", "部署到 fly.io，两个区域", "project:new", "deploy_target", "fly.io 两个区域", "fly.io", "MERGE", None, None, "user_direct", ""),
    ("test-merge-03", "评审人钱七，加急时可以直接找王五", "project:new", "reviewer", "钱七 加急找王五", "钱七", "MERGE", None, None, "user_direct", ""),
    # SUPERSEDE 4
    ("test-sup-01", "现在改用 yarn 了", _PROJ, _PM, "yarn", "pnpm", "SUPERSEDE", None, None, "user_direct", ""),
    ("test-sup-02", "测试已经迁移到 vitest", _PROJ, "test_command", "vitest", "pytest", "SUPERSEDE", None, None, "user_direct", ""),
    ("test-sup-03", "默认分支改成 develop", _PROJ, "default_branch", "develop", "main", "SUPERSEDE", None, None, "user_direct", ""),
    ("test-sup-04", "值班人现在是孙八", _PROJ, "oncall_owner", "孙八", "张三", "SUPERSEDE", None, None, "user_direct", ""),
    # BRANCH 4
    ("test-branch-01", "赶进度的时候部署到临时环境", _PROJ, "deploy_target", "临时环境", "k8s", "BRANCH", "rush", "normal", "user_direct", ""),
    ("test-branch-02", "生产用 postgres", _PROJ, "test_command", "postgres", "sqlite", "BRANCH", "prod", "local", "user_direct", ""),
    ("test-branch-03", "重构时用 mypy strict", _PROJ, "code_style", "mypy strict", "ruff", "BRANCH", "refactor", "feature", "user_direct", ""),
    ("test-branch-04", "晚上值班找小李", _PROJ, "oncall_owner", "小李", "张三", "BRANCH", "night", "day", "user_direct", ""),
    # CONFLICT 3
    ("test-conf-01", "客户助理说他不吃牛肉", "user:bob", "dietary_restriction", "不吃牛肉", "吃牛肉", "CONFLICT", None, None, "third_party", ""),
    ("test-conf-02", "看起来用的是 deno", "project:new", _PM, "deno", "bun", "CONFLICT", None, None, "system_inferred", ""),
    ("test-conf-03", "转述说默认分支是 master", "project:new", "default_branch", "master", "main", "CONFLICT", None, None, "third_party", ""),
]


def _to_dict(case: Case) -> dict[str, object]:
    (
        case_id,
        text,
        subject,
        relation,
        candidate,
        existing,
        expected,
        condition,
        existing_condition,
        authority,
        note,
    ) = case
    payload: dict[str, object] = {
        "id": case_id,
        "text": text,
        "subject": subject,
        "relation": relation,
        "candidate_value": candidate,
        "existing_value": existing,
        "expected": expected,
        "label_status": "proposed",
        "authority": authority,
    }
    if condition:
        payload["condition"] = condition
    if existing_condition:
        payload["existing_condition"] = existing_condition
    if note:
        payload["note"] = note
    return payload


def write(path: Path, cases: list[Case]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(_to_dict(case), ensure_ascii=False) for case in cases]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{path.name}: {len(cases)} 条")


def main() -> int:
    write(TARGET / "dev.jsonl", DEV)
    write(TARGET / "test.jsonl", TEST)
    total = len(DEV) + len(TEST)
    print(f"合计 {total} 条，全部为 proposed，需人工确认后才作为验收依据。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
