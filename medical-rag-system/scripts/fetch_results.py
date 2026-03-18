import argparse
import json
import sys
from pathlib import Path
import urllib.request

from experiment_utils import write_run_artifacts


DEFAULT_OUTPUT_ROOT = Path(__file__).resolve().parent.parent / "experiment_outputs"
DEFAULT_LATEST_REPORT = Path(__file__).resolve().parent / "experiment_results.md"


def _fetch_json(url: str) -> dict:
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description="拉取实验结果并重新导出归档文件")
    parser.add_argument("--api-base", default="http://localhost:8001", help="后端 API 地址")
    parser.add_argument("--run-id", default="", help="指定 run_id；为空时默认取最新一次")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT), help="实验结果归档目录")
    parser.add_argument("--latest-report", default=str(DEFAULT_LATEST_REPORT), help="最新实验摘要 Markdown 输出路径")
    args = parser.parse_args()

    try:
        run_id = args.run_id.strip()
        if not run_id:
            runs = _fetch_json(f"{args.api_base}/api/v1/experiments/runs").get("data", {}).get("items", [])
            if not runs:
                print("没有实验记录")
                sys.exit(1)
            run_id = runs[0]["run_id"]

        run_payload = _fetch_json(f"{args.api_base}/api/v1/experiments/runs/{run_id}").get("data", {})
        if not run_payload:
            print(f"未找到实验记录: {run_id}")
            sys.exit(1)

        output_dir = write_run_artifacts(
            run_payload,
            Path(args.output_root),
            latest_markdown_path=Path(args.latest_report),
        )
        print(f"已导出实验结果: {run_id}")
        print(f"归档目录: {output_dir}")
        print(f"最新摘要: {args.latest_report}")
    except Exception as exc:
        print(f"导出实验结果失败: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
