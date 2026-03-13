import json
import urllib.request
import sys

try:
    req = urllib.request.Request("http://localhost:8001/api/v1/experiments/runs")
    with urllib.request.urlopen(req) as response:
        data = json.loads(response.read().decode())
    runs = data.get("data", {}).get("items", [])
    if not runs:
        print("No runs found")
        sys.exit(1)
        
    latest_run = runs[0]
    metrics = latest_run["metrics"]
    
    output = []
    output.append("# 实验结果报告")
    output.append(f"**实验 ID**: `{latest_run['run_id']}`")
    output.append(f"**模式**: `baseline vs hybrid+rerank`")
    output.append(f"**测试用例数**: {metrics['total_cases']}")
    output.append("")
    output.append("## 指标对比 (Top@5)")
    output.append("| 指标 | Baseline (Vector-only) | Improved (Hybrid+Rerank) |")
    output.append("|---|---|---|")
    output.append(f"| Recall@5 | {metrics['baseline']['recall@5']} | {metrics['improved']['recall@5']} |")
    output.append(f"| MRR | {metrics['baseline']['mrr']} | {metrics['improved']['mrr']} |")
    output.append("")
    output.append("## 逐条结果")
    for i, c in enumerate(metrics.get("cases", []), 1):
        q = c["query"].replace("\n", " ")
        output.append(f"**{i}. {q}**")
        output.append(f"- Baseline Recall: {c.get('baseline_recall@5')}")
        output.append(f"- Improved Recall: {c.get('improved_recall@5')}")
        output.append("")

    with open("c:/Users/lmd16/Desktop/medical-rag-system/medical-rag-system/scripts/experiment_results.md", "w", encoding="utf-8") as f:
        f.write("\n".join(output))
    print("Results saved")

except Exception as e:
    print(f"Error: {e}")
