import csv
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List


def load_dataset(dataset_path: Path) -> List[Dict[str, Any]]:
    raw = json.loads(dataset_path.read_text(encoding="utf-8"))
    cases_raw = raw.get("dataset", raw) if isinstance(raw, dict) else raw
    cases: List[Dict[str, Any]] = []
    for index, case in enumerate(cases_raw, start=1):
        cases.append(
            {
                "case_id": case.get("case_id") or f"case_{index:02d}",
                "query": case["query"],
                "relevant_doc_ids": list(case.get("relevant_doc_ids", [])),
                "relevant_chunk_ids": list(case.get("relevant_chunk_ids", [])),
                "notes": case.get("notes"),
            }
        )
    return cases


def compute_dataset_version(cases: List[Dict[str, Any]]) -> str:
    normalized = []
    for case in cases:
        normalized.append(
            {
                "case_id": case["case_id"],
                "query": case["query"],
                "relevant_doc_ids": sorted(case.get("relevant_doc_ids", [])),
                "relevant_chunk_ids": sorted(case.get("relevant_chunk_ids", [])),
                "notes": case.get("notes") or "",
            }
        )
    raw = json.dumps(normalized, ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def build_doc_alias_map(docs: List[Dict[str, Any]]) -> Dict[str, str]:
    alias_map: Dict[str, str] = {}
    for doc in docs:
        title = (doc.get("title") or "").strip()
        if not title:
            continue
        alias_map[title] = doc["doc_id"]
        for token in title.replace("（", "_").replace("）", "_").replace("-", "_").split("_"):
            token = token.strip()
            if len(token) > 1:
                alias_map[token] = doc["doc_id"]
    return alias_map


def resolve_relevant_doc_ids(cases: List[Dict[str, Any]], docs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    alias_map = build_doc_alias_map(docs)
    resolved_cases: List[Dict[str, Any]] = []
    for case in cases:
        matched_ids = []
        for keyword in case.get("relevant_doc_ids", []):
            for alias, doc_id in alias_map.items():
                if keyword in alias or alias in keyword:
                    matched_ids.append(doc_id)
        resolved_cases.append(
            {
                "case_id": case["case_id"],
                "query": case["query"],
                "relevant_doc_ids": sorted(set(matched_ids)),
                "relevant_chunk_ids": list(case.get("relevant_chunk_ids", [])),
                "notes": case.get("notes"),
                "doc_aliases": list(case.get("relevant_doc_ids", [])),
            }
        )
    return resolved_cases


def write_run_artifacts(
    run_payload: Dict[str, Any],
    output_root: Path,
    *,
    latest_markdown_path: Path | None = None,
) -> Path:
    run_id = run_payload["run_id"]
    target_dir = output_root / run_id
    target_dir.mkdir(parents=True, exist_ok=True)

    run_json_path = target_dir / "run.json"
    cases_csv_path = target_dir / "cases.csv"
    report_md_path = target_dir / "report.md"

    run_json_path.write_text(json.dumps(run_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_cases_csv(run_payload, cases_csv_path)
    report_text = _build_report_markdown(run_payload)
    report_md_path.write_text(report_text, encoding="utf-8")
    if latest_markdown_path is not None:
        latest_markdown_path.parent.mkdir(parents=True, exist_ok=True)
        latest_markdown_path.write_text(report_text, encoding="utf-8")
    return target_dir


def _write_cases_csv(run_payload: Dict[str, Any], csv_path: Path) -> None:
    metrics = run_payload.get("metrics", {})
    cases = metrics.get("cases", [])
    fieldnames = [
        "run_id",
        "case_id",
        "query",
        "group",
        "rank",
        "chunk_id",
        "doc_id",
        "article_no",
        "section",
        "matched_relevant_chunk",
        "matched_relevant_doc",
        "recall@5",
        "hit@5",
        "mrr",
        "first_hit_rank",
        "bm25",
        "vector",
        "rrf",
        "rerank",
        "snippet",
    ]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for case in cases:
            groups = case.get("groups", {})
            for group_name, group_data in groups.items():
                entries = group_data.get("entries", [])
                if not entries:
                    writer.writerow(
                        {
                            "run_id": run_payload["run_id"],
                            "case_id": case.get("case_id"),
                            "query": case.get("query"),
                            "group": group_name,
                            "recall@5": group_data.get("recall@5"),
                            "hit@5": group_data.get("hit@5"),
                            "mrr": group_data.get("mrr"),
                            "first_hit_rank": group_data.get("first_hit_rank"),
                        }
                    )
                    continue
                for entry in entries:
                    writer.writerow(
                        {
                            "run_id": run_payload["run_id"],
                            "case_id": case.get("case_id"),
                            "query": case.get("query"),
                            "group": group_name,
                            "rank": entry.get("rank"),
                            "chunk_id": entry.get("chunk_id"),
                            "doc_id": entry.get("doc_id"),
                            "article_no": entry.get("article_no"),
                            "section": entry.get("section"),
                            "matched_relevant_chunk": entry.get("matched_relevant_chunk"),
                            "matched_relevant_doc": entry.get("matched_relevant_doc"),
                            "recall@5": group_data.get("recall@5"),
                            "hit@5": group_data.get("hit@5"),
                            "mrr": group_data.get("mrr"),
                            "first_hit_rank": group_data.get("first_hit_rank"),
                            "bm25": entry.get("scores", {}).get("bm25"),
                            "vector": entry.get("scores", {}).get("vector"),
                            "rrf": entry.get("scores", {}).get("rrf"),
                            "rerank": entry.get("scores", {}).get("rerank"),
                            "snippet": entry.get("snippet"),
                        }
                    )


def _build_report_markdown(run_payload: Dict[str, Any]) -> str:
    config = run_payload.get("config", {})
    metrics = run_payload.get("metrics", {})
    groups = metrics.get("groups", {})
    lines = [
        "# 实验结果报告",
        f"**实验 ID**: `{run_payload['run_id']}`",
        f"**模式**: `{run_payload.get('mode', 'unknown')}`",
        f"**运行时间**: `{run_payload.get('created_at', '')}`",
        "",
        "## 版本信息",
        f"- dataset_version: `{config.get('dataset_version', '')}`",
        f"- corpus_version: `{config.get('corpus_version', '')}`",
        f"- chunk_strategy_version: `{config.get('chunk_strategy_version', '')}`",
        f"- vector_backend: `{config.get('vector_backend', '')}`",
        f"- embedding: `{config.get('embedding_provider', '')}` / `{config.get('embedding_model', '')}`",
        f"- rerank: `{config.get('rerank_provider', '')}` / `{config.get('rerank_model', '')}`",
        "",
        "## 组间指标对比",
        "| Group | Recall@5 | Hit@5 | MRR |",
        "|---|---:|---:|---:|",
    ]
    for group_name in ("bm25_only", "vector_only", "hybrid_no_rerank", "hybrid_rerank"):
        group = groups.get(group_name, {})
        lines.append(
            f"| {group_name} | {group.get('recall@5', 0)} | {group.get('hit@5', 0)} | {group.get('mrr', 0)} |"
        )

    lines.extend(
        [
            "",
            "## 兼容视图",
            f"- baseline(vector_only): Recall@5={metrics.get('baseline', {}).get('recall@5', 0)}, MRR={metrics.get('baseline', {}).get('mrr', 0)}",
            f"- improved(hybrid_rerank): Recall@5={metrics.get('improved', {}).get('recall@5', 0)}, MRR={metrics.get('improved', {}).get('mrr', 0)}",
            "",
            "## 样例明细",
        ]
    )
    for case in metrics.get("cases", [])[:8]:
        lines.append(f"### {case.get('case_id')} - {case.get('query')}")
        for group_name in ("bm25_only", "vector_only", "hybrid_no_rerank", "hybrid_rerank"):
            group = case.get("groups", {}).get(group_name, {})
            lines.append(
                f"- {group_name}: Recall@5={group.get('recall@5', 0)}, Hit@5={group.get('hit@5', 0)}, MRR={group.get('mrr', 0)}, first_hit_rank={group.get('first_hit_rank')}"
            )
        lines.append("")
    return "\n".join(lines).strip() + "\n"
