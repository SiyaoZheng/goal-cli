#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass(frozen=True)
class ChecklistItem:
    code: str
    text: str
    mode: str
    suite: str
    line: int


@dataclass(frozen=True)
class ItemResult:
    item: ChecklistItem
    status: str
    reason: str


CheckFn = Callable[[str, dict[str, str]], tuple[str, str]]


ROOT = Path(__file__).resolve().parents[1]
CHECKLIST_PATH = Path(os.environ.get("DP16276_CHECKLIST_PATH", ROOT / "checklists" / "dp16276-tdd-checklist.md"))
MANUAL_RESULTS_PATH = Path(os.environ.get("DP16276_MANUAL_RESULTS", ROOT / "checklists" / "dp16276-manual-results.json"))


def main() -> int:
    artifact_env = os.environ.get("GOAL_ARTIFACT")
    if not artifact_env:
        print_verdict("GOAL_ARTIFACT is not set.", None, [], [], {})
        return 2

    artifact_path = Path(artifact_env)
    artifact_sha = sha256_file(artifact_path) if artifact_path.exists() else ""
    if not artifact_path.exists():
        print_verdict(f"Configured artifact does not exist: {artifact_path}", artifact_sha, [], [], {})
        return 1

    checklist_items = parse_checklist(CHECKLIST_PATH)
    manual_results = load_manual_results(MANUAL_RESULTS_PATH)
    text, extraction_error = extract_artifact_text(artifact_path)
    sections = section_texts(text)

    results: list[ItemResult] = []
    if extraction_error:
        results.append(
            ItemResult(
                ChecklistItem("ARTIFACT-EXTRACTION", extraction_error, "M", "artifact", 0),
                "fail",
                "Could not extract manuscript text for checklist evaluation.",
            )
        )

    for item in checklist_items:
        results.append(evaluate_item(item, text, sections, manual_results))

    counts = count_statuses(results)
    blockers = [result for result in results if result.status == "fail"]
    ready = not blockers
    report = {
        "artifact": str(artifact_path),
        "artifact_sha256": artifact_sha,
        "checklist": str(CHECKLIST_PATH),
        "manual_results": str(MANUAL_RESULTS_PATH),
        "counts": counts,
        "results": [
            {
                "code": result.item.code,
                "suite": result.item.suite,
                "mode": result.item.mode,
                "status": result.status,
                "reason": result.reason,
                "line": result.item.line,
            }
            for result in results
        ],
    }
    write_run_report(report)
    print_report(ready, artifact_sha, checklist_items, counts, blockers)
    return 0


def parse_checklist(path: Path) -> list[ChecklistItem]:
    text = path.read_text(encoding="utf-8")
    suite = "unknown"
    items: list[ChecklistItem] = []
    item_re = re.compile(r"^- \[ \] \*\*([A-Z0-9-]+)\*\*\s+(.*?)\s*\(([MHR])\)\s*$")
    for line_no, line in enumerate(text.splitlines(), start=1):
        if line.startswith("## Suite "):
            suite = line.lstrip("# ").strip()
        match = item_re.match(line.strip())
        if match:
            items.append(ChecklistItem(match.group(1), match.group(2), match.group(3), suite, line_no))
    return items


def load_manual_results(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"manual results must be a JSON object: {path}")
    return payload


def evaluate_item(item: ChecklistItem, text: str, sections: dict[str, str], manual_results: dict[str, object]) -> ItemResult:
    manual = manual_result(item.code, manual_results)
    if manual is not None:
        status, reason = manual
        return ItemResult(item, status, reason)

    check = AUTO_CHECKS.get(item.code)
    if check is not None:
        status, reason = check(text, sections)
        return ItemResult(item, status, reason)

    reason = "No deterministic rule is mapped for this item; add it to dp16276-manual-results.json after reviewing the artifact."
    if item.mode == "M":
        reason = "Machine-checkable item is not implemented in this example runner yet; add a manual result or extend AUTO_CHECKS."
    return ItemResult(item, "fail", reason)


def manual_result(code: str, manual_results: dict[str, object]) -> tuple[str, str] | None:
    if code not in manual_results:
        return None
    value = manual_results[code]
    if isinstance(value, bool):
        return ("pass" if value else "fail", "Manual checklist result.")
    if isinstance(value, dict):
        raw_status = value.get("status")
        if raw_status is None and "pass" in value:
            raw_status = "pass" if value.get("pass") else "fail"
        status = str(raw_status or "").strip().lower()
        if status in {"pass", "passed", "true"}:
            status = "pass"
        elif status in {"na", "n/a", "not_applicable", "not applicable"}:
            status = "na"
        else:
            status = "fail"
        note = str(value.get("note") or "Manual checklist result.").strip()
        return status, note
    return "fail", "Manual result must be boolean or an object with pass/status."


def extract_artifact_text(path: Path) -> tuple[str, str | None]:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return extract_pdf_text(path)
    try:
        return path.read_text(encoding="utf-8", errors="replace"), None
    except OSError as exc:
        return "", str(exc)


def extract_pdf_text(path: Path) -> tuple[str, str | None]:
    pdftotext = shutil.which("pdftotext")
    if pdftotext:
        try:
            completed = subprocess.run(
                [pdftotext, "-layout", str(path), "-"],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=60,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return "", str(exc)
        if completed.returncode == 0 and completed.stdout.strip():
            return completed.stdout, None
        return "", completed.stderr.strip() or "pdftotext returned no text."
    return "", "pdftotext is not available; use a text artifact or install poppler."


def section_texts(text: str) -> dict[str, str]:
    headings = []
    for match in re.finditer(r"(?m)^\s{0,3}(#{1,6})\s+(.+?)\s*$", text):
        headings.append((match.start(), match.end(), len(match.group(1)), clean_heading(match.group(2))))
    if not headings:
        return {"body": text}
    sections: dict[str, str] = {}
    for index, (_, end, level, title) in enumerate(headings):
        next_start = len(text)
        for next_heading in headings[index + 1 :]:
            if next_heading[2] <= level:
                next_start = next_heading[0]
                break
        sections[title] = text[end:next_start]
    return sections


def clean_heading(value: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", value.lower()).strip()


def first_title(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip(" #\t")
        if stripped:
            return stripped
    return ""


def combined_section(sections: dict[str, str], *needles: str) -> str:
    chunks = []
    for heading, body in sections.items():
        if any(needle in heading for needle in needles):
            chunks.append(body)
    return "\n".join(chunks)


def body_or_section(text: str, sections: dict[str, str], *needles: str) -> str:
    body = combined_section(sections, *needles)
    return body if body.strip() else text


def has_any(text: str, *patterns: str) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE) for pattern in patterns)


def pass_if(condition: bool, pass_reason: str, fail_reason: str) -> tuple[str, str]:
    return ("pass", pass_reason) if condition else ("fail", fail_reason)


def title_short(text: str, _: dict[str, str]) -> tuple[str, str]:
    title = first_title(text)
    words = re.findall(r"\w+", title)
    return pass_if(bool(title) and len(words) <= 18, "Title is present and at most 18 words.", "Title is missing or longer than 18 words.")


def title_not_evidence_from(text: str, _: dict[str, str]) -> tuple[str, str]:
    title = first_title(text)
    return pass_if("evidence from" not in title.lower(), "Title avoids the formulaic 'Evidence from...' pattern.", "Title uses 'Evidence from...'.")


def abstract_has_question(text: str, sections: dict[str, str]) -> tuple[str, str]:
    abstract = body_or_section(text, sections, "abstract", "摘要")
    return pass_if(
        has_any(abstract, r"\bresearch question\b", r"\bwe (ask|examine|study|investigate|estimate)\b", r"研究问题", r"本文(研究|考察|检验)"),
        "Abstract states a detectable research question or study verb.",
        "Abstract does not clearly state a research question.",
    )


def abstract_has_design(text: str, sections: dict[str, str]) -> tuple[str, str]:
    abstract = body_or_section(text, sections, "abstract", "摘要")
    return pass_if(
        has_any(abstract, r"\b(data|dataset|survey|experiment|panel|rdd|iv|did|difference[- ]in[- ]differences)\b", r"数据|样本|实验|面板|断点|工具变量|双重差分"),
        "Abstract names data or research design.",
        "Abstract does not name data or research design.",
    )


def abstract_has_quant_result(text: str, sections: dict[str, str]) -> tuple[str, str]:
    abstract = body_or_section(text, sections, "abstract", "摘要")
    return pass_if(
        has_any(abstract, r"\d+(\.\d+)?\s*(%|percent|percentage points|pp|standard deviations|sd|倍|个百分点|标准差)"),
        "Abstract reports at least one quantitative result.",
        "Abstract lacks a detectable quantitative result.",
    )


def has_this_paper_examines(text: str, _: dict[str, str]) -> tuple[str, str]:
    early = "\n".join(text.splitlines()[:80])
    return pass_if(
        has_any(early, r"\bthis paper (examines|studies|investigates|estimates|asks)\b", r"本文(研究|考察|检验|估计)"),
        "A 'this paper...' style statement appears early.",
        "No detectable 'this paper examines...' equivalent appears early.",
    )


def data_source_period(text: str, sections: dict[str, str]) -> tuple[str, str]:
    data = body_or_section(text, sections, "data", "数据")
    has_source = has_any(data, r"\b(source|dataset|survey|administrative|census)\b", r"来源|数据集|调查|普查|行政")
    has_years = has_any(data, r"\b(19|20)\d{2}\s*[-–]\s*(19|20)\d{2}\b", r"\b(19|20)\d{2}\b")
    return pass_if(has_source and has_years, "Data section names a source and time coverage.", "Data source or time coverage is not detectable.")


def data_structure(text: str, sections: dict[str, str]) -> tuple[str, str]:
    data = body_or_section(text, sections, "data", "数据")
    return pass_if(
        has_any(data, r"\b(panel|cross[- ]section|time[- ]series)\b", r"面板|截面|时间序列"),
        "Data structure is stated.",
        "Panel, cross-section, or time-series structure is not detectable.",
    )


def data_sample_size(text: str, sections: dict[str, str]) -> tuple[str, str]:
    data = body_or_section(text, sections, "data", "数据")
    return pass_if(
        has_any(data, r"\b(N|n|sample|observations?)\s*[=:]?\s*[0-9,]+", r"样本量|观测(值|数)?"),
        "Sample size or observation count is detectable.",
        "Sample size or observation count is not detectable.",
    )


def summary_stats(text: str, _: dict[str, str]) -> tuple[str, str]:
    return pass_if(
        has_any(text, r"summary statistics", r"descriptive statistics", r"mean", r"standard deviation", r"std\.? dev", r"描述性统计|汇总统计|均值|标准差"),
        "Summary-statistics language is detectable.",
        "Summary statistics are not detectable.",
    )


def identification_design(text: str, sections: dict[str, str]) -> tuple[str, str]:
    methods = body_or_section(text, sections, "identification", "empirical", "method", "识别", "方法")
    return pass_if(
        has_any(methods, r"\b(rct|experiment|natural experiment|rdd|regression discontinuity|iv|instrumental variable|did|difference[- ]in[- ]differences)\b", r"随机实验|自然实验|断点|工具变量|双重差分"),
        "Identification design is named.",
        "Identification design is not named.",
    )


def equation_present(text: str, sections: dict[str, str]) -> tuple[str, str]:
    methods = body_or_section(text, sections, "identification", "empirical", "method", "识别", "方法")
    return pass_if(
        has_any(methods, r"\\begin\{equation\}", r"\$[^$=]{1,80}=[^$]{1,160}\$", r"\bY_{?i", r"β|\\beta"),
        "An estimating equation is detectable.",
        "No estimating equation is detectable.",
    )


def references_present(text: str, _: dict[str, str]) -> tuple[str, str]:
    return pass_if(
        has_any(text, r"(?m)^#+\s*(references|bibliography|works cited)\b", r"参考文献"),
        "References section is present.",
        "References section is not detectable.",
    )


def figures_tables_numbered(text: str, _: dict[str, str]) -> tuple[str, str]:
    return pass_if(
        has_any(text, r"\b(Figure|Fig\.)\s+\d+", r"\bTable\s+\d+", r"图\s*\d+|表\s*\d+"),
        "Numbered figures or tables are detectable.",
        "Numbered figures or tables are not detectable.",
    )


AUTO_CHECKS: dict[str, CheckFn] = {
    "TITLE-002": title_short,
    "TITLE-008": title_not_evidence_from,
    "ABS-002": abstract_has_question,
    "ABS-003": abstract_has_design,
    "ABS-004": abstract_has_quant_result,
    "INTRO-009": has_this_paper_examines,
    "DATA-002": data_source_period,
    "DATA-003": data_structure,
    "DATA-004": data_sample_size,
    "DATA-012": summary_stats,
    "DATA-013": summary_stats,
    "ID-004": identification_design,
    "ID-012": equation_present,
    "LIT-020": references_present,
    "FMT-008": figures_tables_numbered,
}


def count_statuses(results: list[ItemResult]) -> dict[str, int]:
    counts = {"pass": 0, "fail": 0, "na": 0}
    for result in results:
        counts[result.status] = counts.get(result.status, 0) + 1
    return counts


def print_report(ready: bool, artifact_sha: str, items: list[ChecklistItem], counts: dict[str, int], blockers: list[ItemResult]) -> None:
    print("# DP16276 Economics Writing Checklist")
    print()
    print(f"- Checklist file: {CHECKLIST_PATH}")
    print(f"- Parsed checklist items: {len(items)}")
    print(f"- Manual results file: {MANUAL_RESULTS_PATH}")
    print(f"- PASS: {counts.get('pass', 0)}")
    print(f"- FAIL: {counts.get('fail', 0)}")
    print(f"- N/A: {counts.get('na', 0)}")
    print()
    if blockers:
        print("## Blocking Checklist Items")
        print()
        for result in blockers[:80]:
            print(f"- **{result.item.code}** ({result.item.mode}) {result.item.text}")
            print(f"  - {result.reason}")
        if len(blockers) > 80:
            print(f"- ... {len(blockers) - 80} additional blocking items omitted from stdout; see the JSON report in GOAL_RUN_DIR.")
    else:
        print("All checklist items passed or were marked not applicable.")
    print()
    print("```json")
    print(
        json.dumps(
            {
                "artifact_ready": ready,
                "review_matches_current_artifact": True,
                "current_artifact_sha256": artifact_sha,
                "blocking_objections": [f"{result.item.code}: {result.reason}" for result in blockers[:50]],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    print("```")


def print_verdict(message: str, artifact_sha: str | None, items: list[ChecklistItem], blockers: list[ItemResult], counts: dict[str, int]) -> None:
    _ = items, blockers, counts
    print("# DP16276 Economics Writing Checklist")
    print()
    print(message)
    print()
    print("```json")
    print(
        json.dumps(
            {
                "artifact_ready": False,
                "review_matches_current_artifact": bool(artifact_sha),
                "current_artifact_sha256": artifact_sha or "",
                "blocking_objections": [message],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    print("```")


def write_run_report(report: dict[str, object]) -> None:
    run_dir = os.environ.get("GOAL_RUN_DIR")
    if not run_dir:
        return
    path = Path(run_dir) / "dp16276_checklist_results.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as input_file:
        for chunk in iter(lambda: input_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print("# DP16276 Economics Writing Checklist")
        print()
        print(f"Checklist runner failed: {exc}", file=sys.stdout)
        print()
        print("```json")
        print(
            json.dumps(
                {
                    "artifact_ready": False,
                    "review_matches_current_artifact": False,
                    "current_artifact_sha256": "",
                    "blocking_objections": [str(exc)],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        print("```")
        raise SystemExit(1)
