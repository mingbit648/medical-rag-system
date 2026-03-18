import argparse
import json
import sys
from pathlib import Path

import httpx

from experiment_utils import compute_dataset_version, load_dataset


DEFAULT_DATASET_PATH = Path(__file__).resolve().parent / "test_dataset.json"
DEFAULT_OUTPUT_ROOT = Path(__file__).resolve().parent.parent / "experiment_outputs"


def main() -> None:
    parser = argparse.ArgumentParser(description="为实验数据集生成 chunk 标注候选")
    parser.add_argument("--api-base", default="http://localhost:8001", help="后端 API 地址")
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET_PATH), help="实验数据集路径")
    parser.add_argument("--topk", type=int, default=12, help="每题导出的候选 chunk 数量")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT), help="输出目录")
    args = parser.parse_args()

    dataset_path = Path(args.dataset)
    if not dataset_path.exists():
        print(f"数据集不存在: {dataset_path}")
        sys.exit(1)

    cases = load_dataset(dataset_path)
    dataset_version = compute_dataset_version(cases)
    client = httpx.Client(base_url=args.api_base, timeout=300.0)

    try:
        docs_resp = client.get("/api/v1/docs")
        docs_resp.raise_for_status()
        docs = docs_resp.json()["data"]["items"]
    except Exception as exc:
        print(f"无法获取文档列表: {exc}")
        sys.exit(1)

    doc_title_map = {doc["doc_id"]: doc.get("title", "") for doc in docs}
    output_payload = {
        "dataset_version": dataset_version,
        "topk": args.topk,
        "cases": [],
    }

    for case in cases:
        try:
            resp = client.post(
                "/api/v1/retrieve/debug",
                json={
                    "query": case["query"],
                    "topn": {"bm25": 50, "vector": 50},
                    "fusion": {"method": "rrf", "k": 60},
                    "rerank": {"topk": max(args.topk, 12), "topm": max(args.topk, 12)},
                },
            )
            resp.raise_for_status()
            rerank_items = resp.json()["data"]["rerank"][: args.topk]
        except Exception as exc:
            print(f"生成候选失败: {case['case_id']} - {exc}")
            sys.exit(1)

        output_payload["cases"].append(
            {
                "case_id": case["case_id"],
                "query": case["query"],
                "current_relevant_chunk_ids": case.get("relevant_chunk_ids", []),
                "current_relevant_doc_ids": case.get("relevant_doc_ids", []),
                "candidates": [
                    {
                        "rank": index,
                        "chunk_id": item.get("chunk_id"),
                        "doc_id": item.get("doc_id"),
                        "title": doc_title_map.get(item.get("doc_id"), ""),
                        "article_no": item.get("article_no"),
                        "section": item.get("section"),
                        "scores": {
                            "bm25": item.get("bm25"),
                            "vector": item.get("vector"),
                            "rrf": item.get("rrf"),
                            "rerank": item.get("rerank"),
                        },
                        "snippet": (item.get("chunk_text") or "")[:240],
                    }
                    for index, item in enumerate(rerank_items, start=1)
                ],
            }
        )

    output_dir = Path(args.output_root)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"label_candidates_{dataset_version}.json"
    output_path.write_text(json.dumps(output_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"标注候选已生成: {output_path}")


if __name__ == "__main__":
    main()
