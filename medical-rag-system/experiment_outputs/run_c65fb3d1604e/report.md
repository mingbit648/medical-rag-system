# 实验结果报告
**实验 ID**: `run_c65fb3d1604e`
**模式**: `four_group_retrieval_benchmark`
**运行时间**: `2026-03-18T10:58:52.071019+00:00`

## 版本信息
- dataset_version: `eee99eb9ca846fb3`
- corpus_version: `8a955916d941ab35`
- chunk_strategy_version: `law_structured_v1`
- vector_backend: `memory`
- embedding: `siliconflow` / `hash-256`
- rerank: `siliconflow` / `BAAI/bge-reranker-v2-m3`

## 组间指标对比
| Group | Recall@5 | Hit@5 | MRR |
|---|---:|---:|---:|
| bm25_only | 0.7133 | 0.92 | 0.7007 |
| vector_only | 0.4367 | 0.68 | 0.408 |
| hybrid_no_rerank | 0.5633 | 0.84 | 0.608 |
| hybrid_rerank | 0.6933 | 0.92 | 0.634 |

## 兼容视图
- baseline(vector_only): Recall@5=0.4367, MRR=0.408
- improved(hybrid_rerank): Recall@5=0.6933, MRR=0.634

## 样例明细
### case_01 - 公司连续三个月拖欠工资，劳动者可以怎么维权？
- bm25_only: Recall@5=1.0, Hit@5=1.0, MRR=1.0, first_hit_rank=1
- vector_only: Recall@5=1.0, Hit@5=1.0, MRR=1.0, first_hit_rank=1
- hybrid_no_rerank: Recall@5=1.0, Hit@5=1.0, MRR=1.0, first_hit_rank=1
- hybrid_rerank: Recall@5=1.0, Hit@5=1.0, MRR=1.0, first_hit_rank=1

### case_02 - 劳动合同到期后公司不续签，劳动者能获得什么赔偿？
- bm25_only: Recall@5=0.0, Hit@5=0.0, MRR=0.0, first_hit_rank=None
- vector_only: Recall@5=0.0, Hit@5=0.0, MRR=0.0, first_hit_rank=None
- hybrid_no_rerank: Recall@5=0.0, Hit@5=0.0, MRR=0.0, first_hit_rank=None
- hybrid_rerank: Recall@5=0.0, Hit@5=0.0, MRR=0.0, first_hit_rank=None

### case_03 - 用人单位违法解除劳动合同，劳动者如何申请劳动仲裁？
- bm25_only: Recall@5=0.3333, Hit@5=1.0, MRR=0.2, first_hit_rank=5
- vector_only: Recall@5=0.0, Hit@5=0.0, MRR=0.0, first_hit_rank=None
- hybrid_no_rerank: Recall@5=0.3333, Hit@5=1.0, MRR=0.5, first_hit_rank=2
- hybrid_rerank: Recall@5=0.3333, Hit@5=1.0, MRR=0.25, first_hit_rank=4

### case_04 - 劳动者加班费的计算标准是什么？法定节假日加班如何计算？
- bm25_only: Recall@5=0.0, Hit@5=0.0, MRR=0.0, first_hit_rank=None
- vector_only: Recall@5=0.0, Hit@5=0.0, MRR=0.0, first_hit_rank=None
- hybrid_no_rerank: Recall@5=0.0, Hit@5=0.0, MRR=0.0, first_hit_rank=None
- hybrid_rerank: Recall@5=0.0, Hit@5=0.0, MRR=0.0, first_hit_rank=None

### case_05 - 用人单位未签订书面劳动合同，劳动者有什么权利？
- bm25_only: Recall@5=1.0, Hit@5=1.0, MRR=1.0, first_hit_rank=1
- vector_only: Recall@5=0.0, Hit@5=0.0, MRR=0.0, first_hit_rank=None
- hybrid_no_rerank: Recall@5=0.6667, Hit@5=1.0, MRR=0.5, first_hit_rank=2
- hybrid_rerank: Recall@5=1.0, Hit@5=1.0, MRR=0.5, first_hit_rank=2

### case_06 - 劳动者工伤后有哪些法定的工伤待遇？
- bm25_only: Recall@5=1.0, Hit@5=1.0, MRR=1.0, first_hit_rank=1
- vector_only: Recall@5=0.0, Hit@5=0.0, MRR=0.0, first_hit_rank=None
- hybrid_no_rerank: Recall@5=0.0, Hit@5=0.0, MRR=0.0, first_hit_rank=None
- hybrid_rerank: Recall@5=1.0, Hit@5=1.0, MRR=1.0, first_hit_rank=1

### case_07 - 试用期的最长时间是多少？试用期工资的最低标准是什么？
- bm25_only: Recall@5=0.5, Hit@5=1.0, MRR=1.0, first_hit_rank=1
- vector_only: Recall@5=0.5, Hit@5=1.0, MRR=0.25, first_hit_rank=4
- hybrid_no_rerank: Recall@5=0.5, Hit@5=1.0, MRR=1.0, first_hit_rank=1
- hybrid_rerank: Recall@5=0.5, Hit@5=1.0, MRR=1.0, first_hit_rank=1

### case_08 - 什么情况下可以签订无固定期限劳动合同？
- bm25_only: Recall@5=1.0, Hit@5=1.0, MRR=1.0, first_hit_rank=1
- vector_only: Recall@5=1.0, Hit@5=1.0, MRR=0.3333, first_hit_rank=3
- hybrid_no_rerank: Recall@5=1.0, Hit@5=1.0, MRR=0.5, first_hit_rank=2
- hybrid_rerank: Recall@5=1.0, Hit@5=1.0, MRR=1.0, first_hit_rank=1
