import argparse
import sys
from pathlib import Path

import httpx

from experiment_utils import (
    compute_dataset_version,
    load_dataset,
    resolve_relevant_doc_ids,
    write_run_artifacts,
)


DEFAULT_DATASET_PATH = Path(__file__).resolve().parent / "test_dataset.json"
DEFAULT_OUTPUT_ROOT = Path(__file__).resolve().parent.parent / "experiment_outputs"
DEFAULT_LATEST_REPORT = Path(__file__).resolve().parent / "experiment_results.md"


def main() -> None:
    parser = argparse.ArgumentParser(description="运行 4 组检索对比实验并归档结果")
    parser.add_argument("--api-base", default="http://localhost:8001", help="后端 API 地址")
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET_PATH), help="实验数据集路径")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT), help="实验结果归档目录")
    parser.add_argument("--latest-report", default=str(DEFAULT_LATEST_REPORT), help="最新实验摘要 Markdown 输出路径")
    args = parser.parse_args()

    dataset_path = Path(args.dataset)
    if not dataset_path.exists():
        print(f"数据集不存在: {dataset_path}")
        sys.exit(1)

    raw_cases = load_dataset(dataset_path)
    dataset_version = compute_dataset_version(raw_cases)
    print(f"加载 {len(raw_cases)} 条实验样本，dataset_version={dataset_version}")

    client = httpx.Client(base_url=args.api_base, timeout=600.0)
    try:
        docs_resp = client.get("/api/v1/docs")
        docs_resp.raise_for_status()
        docs = docs_resp.json()["data"]["items"]
    except Exception as exc:
        print(f"无法获取文档列表: {exc}")
        sys.exit(1)

    resolved_cases = resolve_relevant_doc_ids(raw_cases, docs)
    unresolved = [case for case in resolved_cases if not case["relevant_doc_ids"] and not case["relevant_chunk_ids"]]
    if unresolved:
        print("以下样本未能解析出 relevant_doc_ids，且没有 chunk 标注，实验会失真：")
        for case in unresolved:
            print(f"  - {case['case_id']}: {case['query']}")
        sys.exit(1)

    try:
        run_resp = client.post(
            "/api/v1/experiments/run",
            json={
                "dataset": [
                    {
                        "case_id": case["case_id"],
                        "query": case["query"],
                        "relevant_doc_ids": case["relevant_doc_ids"],
                        "relevant_chunk_ids": case["relevant_chunk_ids"],
                        "notes": case.get("notes"),
                    }
                    for case in resolved_cases
                ],
                "dataset_version": dataset_version,
                "topn": {"bm25": 50, "vector": 50},
                "fusion": {"method": "rrf", "k": 60},
                "rerank": {"topk": 30, "topm": 8},
            },
        )
        run_resp.raise_for_status()
        run_payload = run_resp.json()["data"]
    except Exception as exc:
        print(f"实验运行失败: {exc}")
        if getattr(exc, "response", None) is not None:
            print(exc.response.text[:1000])
        sys.exit(1)

    output_dir = write_run_artifacts(
        run_payload,
        Path(args.output_root),
        latest_markdown_path=Path(args.latest_report),
    )

    groups = run_payload.get("metrics", {}).get("groups", {})
    print(f"实验完成: run_id={run_payload['run_id']}")
    for group_name in ("bm25_only", "vector_only", "hybrid_no_rerank", "hybrid_rerank"):
        metrics = groups.get(group_name, {})
        print(
            f"  {group_name:<18} Recall@5={metrics.get('recall@5', 0):.4f} "
            f"Hit@5={metrics.get('hit@5', 0):.4f} MRR={metrics.get('mrr', 0):.4f}"
        )
    print(f"归档目录: {output_dir}")
    print(f"最新摘要: {args.latest_report}")


if __name__ == "__main__":
    main()
