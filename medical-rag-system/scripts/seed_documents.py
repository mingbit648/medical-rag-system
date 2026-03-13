"""
批量导入法律文档到 RAG 系统。

用法：
    python scripts/seed_documents.py [--api-base http://localhost:8001]

依赖：后端服务已启动（PostgreSQL + ChromaDB 也已启动）。
"""

import argparse
import os
import sys
import time
from pathlib import Path

import httpx

DOCS_DIR = Path(__file__).resolve().parent.parent.parent / "国家法律法规数据"


def main():
    parser = argparse.ArgumentParser(description="批量导入法律文档")
    parser.add_argument("--api-base", default="http://localhost:8001", help="后端 API 地址")
    parser.add_argument("--docs-dir", default=str(DOCS_DIR), help="法律文档目录")
    parser.add_argument("--chunk-size", type=int, default=800, help="分块大小")
    parser.add_argument("--chunk-overlap", type=int, default=200, help="分块重叠")
    args = parser.parse_args()

    docs_dir = Path(args.docs_dir)
    if not docs_dir.exists():
        print(f"❌ 文档目录不存在: {docs_dir}")
        sys.exit(1)

    files = sorted(docs_dir.glob("*.docx")) + sorted(docs_dir.glob("*.pdf")) + sorted(docs_dir.glob("*.html"))
    if not files:
        print(f"❌ 未找到文档文件 (.docx/.pdf/.html) 于: {docs_dir}")
        sys.exit(1)

    print(f"📁 找到 {len(files)} 份文档待导入:")
    for f in files:
        print(f"   - {f.name} ({f.stat().st_size / 1024:.1f} KB)")
    print()

    client = httpx.Client(base_url=args.api_base, timeout=120)

    # 检查后端连通
    try:
        r = client.get("/api/v1/docs")
        r.raise_for_status()
        print("✅ 后端连接成功\n")
    except Exception as exc:
        print(f"❌ 无法连接后端 ({args.api_base}): {exc}")
        sys.exit(1)

    results = []
    for idx, file_path in enumerate(files, 1):
        print(f"[{idx}/{len(files)}] 导入: {file_path.name}")

        # Step 1: 导入文档
        with open(file_path, "rb") as f:
            resp = client.post(
                "/api/v1/docs/import",
                files={"file": (file_path.name, f)},
            )
        if resp.status_code != 200:
            print(f"   ❌ 导入失败: {resp.text}")
            continue
        data = resp.json()["data"]
        doc_id = data["doc_id"]
        print(f"   ✅ 导入成功: {doc_id} — {data['title']}")

        # Step 2: 建索引
        resp = client.post(
            f"/api/v1/docs/{doc_id}/index",
            json={
                "chunk": {"size": args.chunk_size, "overlap": args.chunk_overlap},
                "bm25": {"enabled": True},
                "vector": {"enabled": True, "embed_model": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"},
            },
        )
        if resp.status_code != 200:
            print(f"   ❌ 索引失败: {resp.text}")
            continue
        idx_data = resp.json()["data"]
        print(f"   ✅ 索引成功: {idx_data['chunks']} 个分块")
        results.append({"doc_id": doc_id, "title": data["title"], "chunks": idx_data["chunks"], "file": file_path.name})

    print(f"\n{'='*60}")
    print(f"导入完成: {len(results)}/{len(files)} 成功")
    for r in results:
        print(f"  {r['doc_id']}  {r['title']}  ({r['chunks']} chunks)")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
