from __future__ import annotations

import argparse
import json
from pathlib import Path

RANK = {"low": 0, "moderate": 1, "high": 2, "consequential": 3}


def classify(files: list[str]) -> dict[str, object]:
    tier = "low"
    reasons: set[str] = set()
    blockers: set[str] = set()

    def elevate(candidate: str, reason: str) -> None:
        nonlocal tier
        if RANK[candidate] > RANK[tier]:
            tier = candidate
        reasons.add(reason)

    for raw in files:
        path = raw.strip().replace("\\", "/")
        if not path:
            continue
        name = Path(path).name.lower()
        if name == ".env" or name.startswith(".env.") or "credential" in name or "secret" in name:
            elevate("consequential", "secret-bearing or credential-like file changed")
            blockers.add(f"review potential secret-bearing file before promotion: {path}")
        elif path.startswith("flowops/persistence/migrations/"):
            elevate("high", "database migration changed")
        elif path.startswith((".github/workflows/", ".agents/")) or path in {
            "AGENTS.md",
            "pyproject.toml",
        }:
            elevate("high", "repository policy, workflow, dependency or agent contract changed")
        elif path.startswith(
            (
                "flowops/core/",
                "flowops/providers/aws/",
                "flowops/persistence/",
                "flowops/streamlit/",
            )
        ):
            elevate("high", "FlowOps execution/trust/persistence surface changed")
        elif path.startswith(("flowops/", "tests/", "scripts/")) or path == "standalone_app.py":
            elevate("moderate", "runtime, test or executable repository logic changed")
        else:
            reasons.add("documentation or repository metadata changed")

    if not files:
        reasons.add("no changed files supplied")
    return {
        "riskTier": tier,
        "changedFiles": len([item for item in files if item.strip()]),
        "reasons": sorted(reasons),
        "blockingFactors": sorted(blockers),
        "requiresHumanReview": RANK[tier] >= RANK["high"] or bool(blockers),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Classify FlowOps repository change risk")
    parser.add_argument("file", nargs="?", type=Path, help="newline-separated changed-file list")
    args = parser.parse_args()
    text = args.file.read_text(encoding="utf-8") if args.file else __import__("sys").stdin.read()
    result = classify([line for line in text.splitlines() if line.strip()])
    print(json.dumps(result, indent=2))
    return 2 if result["blockingFactors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
