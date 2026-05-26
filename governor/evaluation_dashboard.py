"""Static evaluation dashboard (markdown + HTML) from evaluations.jsonl."""

from __future__ import annotations

import html
import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from governor.evaluation import DASHBOARD_MD, evaluations_dir, load_all_evaluations
from governor.utils import resolve_repo_path

DASHBOARD_HTML = "dashboard.html"

NO_EVALUATIONS_MSG = (
    "No evaluations found. Run: python -m governor evaluate run --run-id <id>"
)

COHORT_FULL_EVIDENCE = "full_with_evidence"
COHORT_FULL_NO_EXPORTS = "full_no_exports"
COHORT_INCOMPLETE = "incomplete_or_failed"
COHORT_SMOKE = "smoke_or_unknown"

MR_OUTCOMES_ORDER = (
    "accepted",
    "needs_minor_changes",
    "needs_major_rewrite",
    "rejected",
    "unknown",
)


@dataclass
class DashboardOptions:
    include_smokes: bool = False
    include_unknown: bool = True
    min_runs_warning: int = 5
    top_n: int = 5


@dataclass
class DashboardResult:
    markdown_path: Path | None = None
    html_path: Path | None = None
    summary: dict[str, Any] = field(default_factory=dict)


def _avg(vals: list[float]) -> float | None:
    return round(sum(vals) / len(vals), 2) if vals else None


def _f(val: Any, default: float = 0.0) -> float:
    if val is None:
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _short_run_id(run_id: str, max_len: int = 42) -> str:
    rid = run_id or ""
    return rid if len(rid) <= max_len else rid[: max_len - 3] + "..."


def infer_cohort(row: dict[str, Any]) -> str:
    mr = str(row.get("mr_outcome") or "unknown").lower()
    outcome = row.get("outcome")
    final_state = str(row.get("final_state") or "")
    has_report = bool(row.get("final_report_exists"))
    has_evidence = bool(row.get("evidence_bundle_exists"))
    has_review = bool(row.get("review_package_exists"))
    completeness = int(row.get("evidence_completeness_score") or 0)

    if outcome != "PASS" or final_state != "FINAL_REPORT_READY":
        if mr == "unknown" and completeness <= 2:
            return COHORT_SMOKE
        return COHORT_INCOMPLETE

    if has_report and has_evidence and has_review:
        return COHORT_FULL_EVIDENCE
    if has_report and (not has_evidence or not has_review):
        return COHORT_FULL_NO_EXPORTS
    if mr == "unknown" and completeness <= 2:
        return COHORT_SMOKE
    if mr == "unknown":
        return COHORT_SMOKE
    return COHORT_INCOMPLETE


def filter_rows(rows: list[dict[str, Any]], opts: DashboardOptions) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        cohort = infer_cohort(row)
        if cohort == COHORT_SMOKE and not opts.include_smokes:
            continue
        if not opts.include_unknown and str(row.get("mr_outcome") or "").lower() == "unknown":
            continue
        out.append({**row, "_cohort": cohort})
    return out


def _annotated_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in rows if r.get("annotations")]


def _group_stats(rs: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = {}
    for r in rs:
        g = str(r.get(key) or "unknown")
        buckets.setdefault(g, []).append(r)
    out: dict[str, dict[str, Any]] = {}
    for g, items in sorted(buckets.items()):
        accepted = sum(1 for r in items if r.get("mr_outcome") == "accepted")
        out[g] = {
            "count": len(items),
            "accepted_count": accepted,
            "avg_friction": _avg([_f(r.get("governor_friction_score")) for r in items]),
            "avg_success": _avg([_f(r.get("run_success_score")) for r in items]),
            "avg_reviewer_signal": _avg(
                [_f(r.get("reviewer_burden_reduction_signal")) for r in items]
            ),
        }
    return out


def _worst_key(r: dict[str, Any]) -> tuple[float, float]:
    return (-_f(r.get("governor_friction_score")), _f(r.get("run_success_score")))


def _best_key(r: dict[str, Any]) -> tuple[float, float]:
    return (_f(r.get("governor_friction_score")), -_f(r.get("run_success_score")))


def build_dashboard_summary(
    all_rows: list[dict[str, Any]],
    filtered: list[dict[str, Any]],
    opts: DashboardOptions,
) -> dict[str, Any]:
    annotated = _annotated_rows(all_rows)
    mr_counts = Counter(str(r.get("mr_outcome") or "unknown") for r in all_rows)
    cohort_counts = Counter(r.get("_cohort", infer_cohort(r)) for r in all_rows)
    gate_counts = Counter(str(r.get("gate_overall") or "none") for r in filtered)

    rework_vals = [
        float(r["manual_rework_minutes"])
        for r in annotated
        if int(r.get("manual_rework_minutes") or 0) > 0
    ]

    defect_counter: Counter[str] = Counter()
    for r in all_rows:
        types = r.get("defect_types") or []
        if isinstance(types, list) and types:
            for t in types:
                defect_counter[str(t)] += 1
        else:
            defect_counter["none/unknown"] += 1

    fake_validator_runs = sum(
        1
        for r in all_rows
        if "fake-validator" in str(r.get("validator_profile") or "").lower()
    )

    return {
        "runs_total": len(all_rows),
        "runs_in_dashboard": len(filtered),
        "annotated_count": len(annotated),
        "mr_outcome_counts": dict(mr_counts),
        "cohort_counts": dict(cohort_counts),
        "gate_overall_counts": dict(gate_counts),
        "outcome_pass_rate": round(
            100.0 * sum(1 for r in filtered if r.get("outcome") == "PASS") / len(filtered),
            1,
        )
        if filtered
        else None,
        "avg_friction": _avg([_f(r.get("governor_friction_score")) for r in filtered]),
        "avg_success": _avg([_f(r.get("run_success_score")) for r in filtered]),
        "avg_reviewer_signal": _avg(
            [_f(r.get("reviewer_burden_reduction_signal")) for r in filtered]
        ),
        "avg_rework_annotated": _avg(rework_vals) if rework_vals else None,
        "smoke_or_unknown_count": cohort_counts.get(COHORT_SMOKE, 0),
        "by_policy": _group_stats(filtered, "policy"),
        "by_executor": _group_stats(filtered, "executor_profile"),
        "by_provider": _group_stats(filtered, "governor_provider"),
        "evidence_bundle_count": sum(1 for r in filtered if r.get("evidence_bundle_exists")),
        "review_package_count": sum(1 for r in filtered if r.get("review_package_exists")),
        "pr_body_count": sum(1 for r in filtered if r.get("pr_body_exists")),
        "avg_evidence_quality": _avg(
            [
                float(r["evidence_quality_score"])
                for r in annotated
                if r.get("evidence_quality_score") is not None
            ]
        ),
        "avg_reviewer_burden_score": _avg(
            [
                float(r["reviewer_burden_score"])
                for r in annotated
                if r.get("reviewer_burden_score") is not None
            ]
        ),
        "defect_type_counts": dict(defect_counter),
        "fake_validator_runs": fake_validator_runs,
        "worst_runs": sorted(filtered, key=_worst_key)[: opts.top_n],
        "best_runs": sorted(filtered, key=_best_key)[: opts.top_n],
        "incomplete_runs": [
            r for r in filtered if r.get("_cohort") == COHORT_INCOMPLETE
        ][: opts.top_n],
        "high_rework_runs": sorted(
            annotated,
            key=lambda r: -int(r.get("manual_rework_minutes") or 0),
        )[: opts.top_n],
        "min_runs_warning": opts.min_runs_warning,
        "include_smokes": opts.include_smokes,
    }


def _md_table(headers: list[str], rows_data: list[list[str]]) -> list[str]:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows_data:
        lines.append("| " + " | ".join(str(c) for c in row) + " |")
    return lines


def _run_row_cells(r: dict[str, Any]) -> list[str]:
    return [
        _short_run_id(str(r.get("run_id") or "")),
        str(r.get("task_category") or r.get("policy") or ""),
        str(r.get("policy") or "unknown"),
        str(r.get("executor_profile") or "unknown"),
        str(r.get("governor_provider") or "unknown"),
        str(r.get("governor_friction_score", "")),
        str(r.get("run_success_score", "")),
        str(r.get("reviewer_burden_reduction_signal", "")),
        str(r.get("mr_outcome") or "unknown"),
        str(r.get("manual_rework_minutes") or 0),
    ]


def render_dashboard_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Governor evaluation dashboard",
        "",
        "Generated from `.governor/evaluations/evaluations.jsonl`. "
        "Scores are heuristics — success means **less manual chaos, rework, and reviewer burden**, "
        "not more agent output.",
        "",
        "## 1. Executive summary",
        "",
        f"- Runs in index: **{summary['runs_total']}**",
        f"- Runs in this dashboard view: **{summary['runs_in_dashboard']}** "
        f"(include_smokes={summary['include_smokes']})",
        f"- Annotated runs: **{summary['annotated_count']}**",
        f"- Average friction (view): **{summary['avg_friction']}** (lower is better)",
        f"- Average success (view): **{summary['avg_success']}**",
        f"- Average reviewer burden signal (view): **{summary['avg_reviewer_signal']}**",
        f"- Average manual rework (annotated, nonzero): **{summary.get('avg_rework_annotated')}** min",
        f"- Outcome PASS rate (view): **{summary.get('outcome_pass_rate')}%**",
        "",
        "### MR outcomes (all runs)",
        "",
    ]
    for mo in MR_OUTCOMES_ORDER:
        c = summary["mr_outcome_counts"].get(mo, 0)
        lines.append(f"- `{mo}`: {c}")
    lines.append("")

    smoke_n = summary.get("smoke_or_unknown_count", 0)
    if smoke_n:
        lines.append(
            f"> **Caveat:** {smoke_n} run(s) classified as `{COHORT_SMOKE}`. "
            "Treat metrics separately from full closures."
        )
        lines.append("")
    if summary["runs_in_dashboard"] < summary["min_runs_warning"]:
        lines.append(
            f"> **Warning:** fewer than {summary['min_runs_warning']} runs in dashboard view — "
            "aggregates may be noisy."
        )
        lines.append("")

    lines.extend(["## 2. Cohort breakdown", ""])
    for cohort in (
        COHORT_FULL_EVIDENCE,
        COHORT_FULL_NO_EXPORTS,
        COHORT_INCOMPLETE,
        COHORT_SMOKE,
    ):
        lines.append(f"- `{cohort}`: {summary['cohort_counts'].get(cohort, 0)}")
    lines.extend(["", "## 3. Gate overall (dashboard view)", ""])
    for gate, cnt in sorted(summary["gate_overall_counts"].items()):
        lines.append(f"- `{gate}`: {cnt}")
    lines.extend(["", "## 4. Friction vs success (all dashboard runs)", ""])
    headers = [
        "run",
        "category",
        "policy",
        "executor",
        "provider",
        "friction",
        "success",
        "reviewer_sig",
        "mr",
        "rework_min",
    ]
    all_view = sorted(
        summary.get("_filtered_rows", []),
        key=_worst_key,
    ) if summary.get("_filtered_rows") else []
    lines.extend(_md_table(headers, [_run_row_cells(r) for r in all_view]))
    lines.append("")

    for title, key in (
        ("## 5. By policy", "by_policy"),
        ("## 6. By executor profile", "by_executor"),
        ("## 7. By governor provider", "by_provider"),
    ):
        lines.extend([title, ""])
        lines.extend(
            _md_table(
                ["group", "count", "accepted", "avg_friction", "avg_success", "avg_reviewer_sig"],
                [
                    [
                        g,
                        str(v["count"]),
                        str(v["accepted_count"]),
                        str(v["avg_friction"]),
                        str(v["avg_success"]),
                        str(v["avg_reviewer_signal"]),
                    ]
                    for g, v in summary[key].items()
                ],
            )
        )
        lines.append("")

    lines.extend(["## 8. Defect types", ""])
    for dt, cnt in sorted(summary["defect_type_counts"].items(), key=lambda x: (-x[1], x[0])):
        lines.append(f"- `{dt}`: {cnt}")
    lines.append("")

    lines.extend(
        [
            "## 9. Reviewer burden / evidence",
            "",
            f"- Evidence bundles: {summary['evidence_bundle_count']}",
            f"- Review packages: {summary['review_package_count']}",
            f"- PR bodies: {summary['pr_body_count']}",
            f"- Avg evidence quality (annotated 1–5): {summary.get('avg_evidence_quality')}",
            f"- Avg reviewer burden score (annotated 1–5, lower better): "
            f"{summary.get('avg_reviewer_burden_score')}",
            "",
        ]
    )

    def _section(title: str, runs: list[dict[str, Any]]) -> None:
        lines.extend([title, ""])
        if not runs:
            lines.append("(none)")
            lines.append("")
            return
        lines.extend(_md_table(headers, [_run_row_cells(r) for r in runs]))
        lines.append("")

    _section("## 10. Runs to inspect — worst (high friction, low success)", summary["worst_runs"])
    _section("## 11. Runs to inspect — best (low friction, high success)", summary["best_runs"])
    _section("## 12. Incomplete runs", summary["incomplete_runs"])
    _section("## 13. High manual rework (annotated)", summary["high_rework_runs"])

    lines.extend(
        [
            "## 14. Notes and caveats",
            "",
            "- Compare runs **within the same `task_category`** — do not rank unrelated tasks.",
            "- **`fake-validator` PASS** means harness success, not production-quality validation.",
        ]
    )
    if summary.get("fake_validator_runs"):
        lines.append(
            f"- This fleet has **{summary['fake_validator_runs']}** run(s) using `fake-validator`."
        )
    lines.extend(
        [
            "- **`unknown` / smoke runs** have lower confidence for MR and rework fields.",
            "- Scores are transparent heuristics in `governor/evaluation.py` — not ground truth.",
            "- Gate **WARN** may come from profile compliance while sub-checks pass.",
            "",
        ]
    )
    return "\n".join(lines)


def _badge_class(label: str) -> str:
    low = label.lower()
    if low in ("pass", "accepted"):
        return "badge-pass"
    if low in ("warn", "needs_minor_changes"):
        return "badge-warn"
    if low in ("fail", "rejected", "needs_major_rewrite"):
        return "badge-fail"
    return "badge-neutral"


def render_dashboard_html(summary: dict[str, Any]) -> str:
    body_parts: list[str] = []
    md_lines = render_dashboard_markdown(summary).split("\n")
    for line in md_lines:
        if line.startswith("# "):
            body_parts.append(f"<h1>{html.escape(line[2:])}</h1>")
        elif line.startswith("## "):
            body_parts.append(f"<h2>{html.escape(line[3:])}</h2>")
        elif line.startswith("### "):
            body_parts.append(f"<h3>{html.escape(line[4:])}</h3>")
        elif line.startswith("> "):
            body_parts.append(f'<p class="caveat">{html.escape(line[2:])}</p>')
        elif line.startswith("| "):
            continue
        elif line.startswith("- "):
            body_parts.append(f"<li>{html.escape(line[2:])}</li>")
        elif line.strip() == "":
            body_parts.append("")
        elif not line.startswith("|---"):
            body_parts.append(f"<p>{html.escape(line)}</p>")

    # Re-render key tables as HTML
    def html_table(headers: list[str], rows_data: list[list[str]]) -> str:
        hdr = "".join(f"<th>{html.escape(h)}</th>" for h in headers)
        rows_html = []
        for row in rows_data:
            cells = "".join(f"<td>{html.escape(c)}</td>" for c in row)
            rows_html.append(f"<tr>{cells}</tr>")
        return (
            '<table class="data">'
            f"<thead><tr>{hdr}</tr></thead>"
            f"<tbody>{''.join(rows_html)}</tbody></table>"
        )

    headers = [
        "run",
        "category",
        "policy",
        "executor",
        "provider",
        "friction",
        "success",
        "reviewer",
        "mr",
        "rework",
    ]
    friction_table = html_table(
        headers,
        [_run_row_cells(r) for r in summary.get("_filtered_rows", [])],
    )

    cohort_badges = " ".join(
        f'<span class="badge badge-neutral">{html.escape(c)}: {n}</span>'
        for c, n in summary["cohort_counts"].items()
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Governor evaluation dashboard</title>
<style>
body {{ font-family: system-ui, sans-serif; margin: 2rem; line-height: 1.45; color: #1a1a1a; }}
h1 {{ border-bottom: 2px solid #333; padding-bottom: 0.3rem; }}
h2 {{ margin-top: 1.5rem; color: #333; }}
.caveat {{ background: #fff8e6; border-left: 4px solid #e6a700; padding: 0.5rem 1rem; }}
table.data {{ border-collapse: collapse; width: 100%; margin: 1rem 0; font-size: 0.9rem; }}
table.data th, table.data td {{ border: 1px solid #ccc; padding: 0.35rem 0.5rem; text-align: left; }}
table.data th {{ background: #f0f0f0; }}
.badge {{ display: inline-block; padding: 0.15rem 0.45rem; margin: 0.1rem; border-radius: 4px; font-size: 0.85rem; }}
.badge-pass {{ background: #d4edda; color: #155724; }}
.badge-warn {{ background: #fff3cd; color: #856404; }}
.badge-fail {{ background: #f8d7da; color: #721c24; }}
.badge-neutral {{ background: #e2e3e5; color: #383d41; }}
ul {{ margin: 0.25rem 0 1rem 1.5rem; }}
</style>
</head>
<body>
<h1>Governor evaluation dashboard</h1>
<p>Local static report — no server, no telemetry. Success = lower rework and reviewer burden.</p>
<h2>Executive summary</h2>
<ul>
<li>Runs: <strong>{summary['runs_total']}</strong> (dashboard view: {summary['runs_in_dashboard']})</li>
<li>Annotated: <strong>{summary['annotated_count']}</strong></li>
<li>Avg friction: <strong>{summary['avg_friction']}</strong></li>
<li>Avg success: <strong>{summary['avg_success']}</strong></li>
<li>Avg reviewer signal: <strong>{summary['avg_reviewer_signal']}</strong></li>
</ul>
<h3>Cohorts</h3>
<p>{cohort_badges}</p>
<h2>Friction vs success</h2>
{friction_table}
<h2>Notes</h2>
<ul>
<li>Compare within same <code>task_category</code>.</li>
<li><strong>fake-validator PASS</strong> is harness success, not production validation.</li>
<li>Unknown/smoke runs have lower confidence.</li>
<li>Scores are heuristics, not absolute truth.</li>
</ul>
</body>
</html>
"""


def generate_dashboard(
    repo_path: Path,
    *,
    fmt: str = "markdown",
    output: Path | None = None,
    include_smokes: bool = False,
    include_unknown: bool = True,
    min_runs: int = 5,
    top_n: int = 5,
) -> DashboardResult:
    repo = resolve_repo_path(str(repo_path))
    all_rows = load_all_evaluations(repo)
    if not all_rows:
        raise FileNotFoundError(NO_EVALUATIONS_MSG)

    opts = DashboardOptions(
        include_smokes=include_smokes,
        include_unknown=include_unknown,
        min_runs_warning=min_runs,
        top_n=top_n,
    )
    filtered = filter_rows(all_rows, opts)
    summary = build_dashboard_summary(all_rows, filtered, opts)
    summary["_filtered_rows"] = sorted(filtered, key=_worst_key)

    ev_dir = evaluations_dir(repo)
    ev_dir.mkdir(parents=True, exist_ok=True)

    fmt_l = fmt.lower()
    result = DashboardResult(summary=summary)

    if fmt_l in ("markdown", "both"):
        md_path = Path(output) if output and fmt_l == "markdown" else ev_dir / DASHBOARD_MD
        if fmt_l == "both":
            md_path = ev_dir / DASHBOARD_MD
        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text(render_dashboard_markdown(summary), encoding="utf-8")
        result.markdown_path = md_path

    if fmt_l in ("html", "both"):
        html_path = Path(output) if output and fmt_l == "html" else ev_dir / DASHBOARD_HTML
        if fmt_l == "both":
            html_path = ev_dir / DASHBOARD_HTML
        html_path.parent.mkdir(parents=True, exist_ok=True)
        html_path.write_text(render_dashboard_html(summary), encoding="utf-8")
        result.html_path = html_path

    return result


# Re-export for evaluation.py index constants
__all__ = [
    "COHORT_FULL_EVIDENCE",
    "COHORT_FULL_NO_EXPORTS",
    "COHORT_INCOMPLETE",
    "COHORT_SMOKE",
    "DASHBOARD_HTML",
    "NO_EVALUATIONS_MSG",
    "DashboardOptions",
    "DashboardResult",
    "build_dashboard_summary",
    "filter_rows",
    "generate_dashboard",
    "infer_cohort",
    "render_dashboard_html",
    "render_dashboard_markdown",
]
