"""
SiliconFlow API 连通性测试脚本。
用法: python scripts/test_siliconflow.py
需要设置环境变量 SILICONFLOW_API_KEY
"""

import json
import os
import sys

import httpx

API_KEY = os.environ.get("SILICONFLOW_API_KEY", "")
BASE_URL = os.environ.get("SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1")
EMBED_MODEL = os.environ.get("SILICONFLOW_EMBED_MODEL", "BAAI/bge-large-zh-v1.5")
RERANK_MODEL = os.environ.get("SILICONFLOW_RERANK_MODEL", "BAAI/bge-reranker-v2-m3")

if not API_KEY:
    print("❌ 请设置环境变量 SILICONFLOW_API_KEY")
    sys.exit(1)

client = httpx.Client(timeout=30.0)
headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
}


def test_embedding():
    print("=" * 50)
    print("📐 测试 Embedding API")
    print(f"   模型: {EMBED_MODEL}")
    print("=" * 50)

    texts = [
        "劳动合同法第四十七条规定了经济补偿的计算方式",
        "用人单位违法解除劳动合同应当支付赔偿金",
        "竞业限制条款的有效期最长不超过两年",
    ]

    resp = client.post(
        f"{BASE_URL}/embeddings",
        headers=headers,
        json={"model": EMBED_MODEL, "input": texts, "encoding_format": "float"},
    )
    resp.raise_for_status()
    data = resp.json()

    print(f"✅ 请求成功!")
    print(f"   返回 {len(data['data'])} 个向量")
    for item in data["data"]:
        dim = len(item["embedding"])
        preview = item["embedding"][:5]
        print(f"   [index={item['index']}] 维度={dim}  前5维={preview}")
    usage = data.get("usage", {})
    print(f"   Token 用量: {usage}")
    return True


def test_rerank():
    print()
    print("=" * 50)
    print("🔄 测试 Rerank API")
    print(f"   模型: {RERANK_MODEL}")
    print("=" * 50)

    query = "劳动合同解除后的经济补偿如何计算"
    documents = [
        "劳动合同法第四十七条：经济补偿按劳动者在本单位工作的年限，每满一年支付一个月工资的标准向劳动者支付。",
        "劳动合同法第八十七条：用人单位违反本法规定解除或者终止劳动合同的，应当依照本法第四十七条规定的经济补偿标准的二倍向劳动者支付赔偿金。",
        "民事诉讼法第一百二十条：起诉应当向人民法院递交起诉状。",
        "竞业限制条款的有效期最长不超过两年，超过部分无效。",
    ]

    resp = client.post(
        f"{BASE_URL}/rerank",
        headers=headers,
        json={
            "model": RERANK_MODEL,
            "query": query,
            "documents": documents,
            "top_n": 4,
            "return_documents": True,
        },
    )
    resp.raise_for_status()
    data = resp.json()

    print(f"✅ 请求成功!")
    results = data.get("results", [])
    print(f"   返回 {len(results)} 个排序结果:")
    for r in results:
        score = r["relevance_score"]
        idx = r["index"]
        doc_preview = documents[idx][:60]
        print(f"   [rank] index={idx}  score={score:.4f}  '{doc_preview}...'")
    return True


if __name__ == "__main__":
    ok = True
    try:
        test_embedding()
    except Exception as e:
        print(f"❌ Embedding 测试失败: {e}")
        ok = False

    try:
        test_rerank()
    except Exception as e:
        print(f"❌ Rerank 测试失败: {e}")
        ok = False

    print()
    if ok:
        print("🎉 所有测试通过！SiliconFlow API 连接正常。")
    else:
        print("⚠️ 部分测试失败，请检查 API Key 和网络连接。")
        sys.exit(1)
