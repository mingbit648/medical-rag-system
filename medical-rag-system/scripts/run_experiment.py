"""
运行对比实验：baseline (vector-only) vs hybrid+rerank。

用法：
    python scripts/run_experiment.py [--api-base http://localhost:8001]

依赖：后端服务已启动且已导入文档（先运行 seed_documents.py）。
"""

import argparse
import json
import sys
from pathlib import Path

import httpx

DATASET_PATH = Path(__file__).resolve().parent / "test_dataset.json"


def main():
    parser = argparse.ArgumentParser(description="运行对比实验")
    parser.add_argument("--api-base", default="http://localhost:8001", help="后端 API 地址")
    parser.add_argument("--dataset", default=str(DATASET_PATH), help="测试集文件路径")
    args = parser.parse_args()

    # 1. 加载测试集
    dataset_path = Path(args.dataset)
    if not dataset_path.exists():
        print(f"❌ 测试集不存在: {dataset_path}")
        sys.exit(1)

    with open(dataset_path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    cases_raw = raw.get("dataset", raw) if isinstance(raw, dict) else raw
    print(f"📋 加载 {len(cases_raw)} 个测试问题\n")

    # 2. 获取已导入文档列表，构建 title → doc_id 映射
    client = httpx.Client(base_url=args.api_base, timeout=600.0)
    try:
        resp = client.get("/api/v1/docs")
        resp.raise_for_status()
        docs = resp.json()["data"]["items"]
    except Exception as exc:
        print(f"❌ 无法获取文档列表: {exc}")
        sys.exit(1)

    title_to_docid = {}
    for doc in docs:
        title_to_docid[doc["title"]] = doc["doc_id"]
        # 也用文件名（去掉扩展名和日期）做模糊匹配
        for keyword in doc["title"].split("_"):
            if len(keyword) > 2:
                title_to_docid[keyword] = doc["doc_id"]

    print(f"📚 系统已有 {len(docs)} 份文档:")
    for d in docs:
        print(f"   {d['doc_id']}  {d['title']}  ({d.get('chunks', '?')} chunks)")
    print()

    # 3. 将 relevant_doc_ids (标题关键词) 映射为实际 doc_id
    experiment_cases = []
    for case in cases_raw:
        query = case["query"]
        doc_keywords = case.get("relevant_doc_ids", [])
        matched_ids = set()
        for keyword in doc_keywords:
            for title, doc_id in title_to_docid.items():
                if keyword in title or title in keyword:
                    matched_ids.add(doc_id)
        experiment_cases.append({
            "query": query,
            "relevant_doc_ids": list(matched_ids),
        })

    matched_count = sum(1 for c in experiment_cases if c["relevant_doc_ids"])
    print(f"🔗 关键词匹配结果: {matched_count}/{len(experiment_cases)} 个问题成功匹配到文档\n")

    if matched_count == 0:
        print("❌ 无任何匹配，请检查文档是否已导入或测试集关键词是否正确")
        sys.exit(1)

    # 4. 运行实验
    print("🧪 开始运行对比实验...\n")
    try:
        resp = client.post(
            "/api/v1/experiments/run",
            json={
                "dataset": experiment_cases,
                "topn": {"bm25": 50, "vector": 50},
                "fusion": {"method": "rrf", "k": 60},
                "rerank": {"topk": 30, "topm": 8},
            },
        )
        resp.raise_for_status()
        result = resp.json()["data"]
    except Exception as exc:
        print(f"❌ 实验运行失败: {exc}")
        if hasattr(exc, "response") and exc.response is not None:
            print(f"   详情: {exc.response.text[:500]}")
        sys.exit(1)

    # 5. 输出结果
    metrics = result["metrics"]
    print(f"{'='*60}")
    print(f"实验 ID: {result['run_id']}")
    print(f"模式: {result['mode']}")
    print(f"测试用例数: {metrics['total_cases']}")
    print(f"{'='*60}")
    print()
    print(f"{'指标':<20} {'Baseline (Vector-only)':<25} {'Improved (Hybrid+Rerank)':<25}")
    print(f"{'-'*70}")
    print(f"{'Recall@5':<20} {metrics['baseline']['recall@5']:<25} {metrics['improved']['recall@5']:<25}")
    print(f"{'MRR':<20} {metrics['baseline']['mrr']:<25} {metrics['improved']['mrr']:<25}")
    print()

    # 逐条结果
    print("逐条结果:")
    for i, case_result in enumerate(metrics.get("cases", []), 1):
        q = case_result["query"][:40]
        b_r = case_result.get("baseline_recall@5", "?")
        i_r = case_result.get("improved_recall@5", "?")
        print(f"  [{i:2d}] {q:<42} baseline_R@5={b_r}  improved_R@5={i_r}")

    print(f"\n{'='*60}")
    print("✅ 实验完成！结果已保存至数据库。")
    print(f"   查看详情: GET {args.api_base}/api/v1/experiments/runs/{result['run_id']}")


if __name__ == "__main__":
    main()
