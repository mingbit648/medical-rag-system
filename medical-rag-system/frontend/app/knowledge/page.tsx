'use client'

import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import Link from 'next/link'
import { Drawer, Empty, Modal, Popconfirm, Progress, Spin, Table, Tabs, Upload, message } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import {
    ArrowLeftOutlined,
    DeleteOutlined,
    DownloadOutlined,
    FileSearchOutlined,
    InboxOutlined,
    MessageOutlined,
    ReloadOutlined,
    ThunderboltOutlined,
} from '@ant-design/icons'
import { resolveApiUrl } from '@/lib/api/client'
import {
    deleteDocument,
    getDocumentDetail,
    importDocuments,
    indexDocument,
    listDocuments,
    type BatchImportProgress,
    type DocStatusResult,
    type DocumentDetail,
    type DocumentDetailChunk,
    type DuplicateDocumentInfo,
} from '@/lib/api/legalRag'

const { Dragger } = Upload

interface DocItem extends DocStatusResult {
    _loading?: 'indexing' | 'deleting'
}

interface UploadSummaryState {
    total: number
    successCount: number
    failureCount: number
    skippedCount: number
    overwrittenCount: number
    failedFiles: string[]
    skippedFiles: string[]
}

const STATUS_MAP: Record<string, { label: string; tone: 'neutral' | 'success' | 'danger' }> = {
    uploaded: { label: '待建索引', tone: 'neutral' },
    imported: { label: '待建索引', tone: 'neutral' },
    indexed: { label: '已完成', tone: 'success' },
    failed: { label: '失败', tone: 'danger' },
}

function formatTime(value: string): string {
    try {
        return new Date(value).toLocaleString('zh-CN', {
            month: '2-digit',
            day: '2-digit',
            hour: '2-digit',
            minute: '2-digit',
        })
    } catch {
        return value
    }
}

function resolveProgressStep(stage: BatchImportProgress['stage']): string {
    if (stage === 'awaiting_confirmation') return '等待覆盖确认'
    if (stage === 'uploading') return '上传中'
    return '建立索引中'
}

function buildUploadPercent(progress: BatchImportProgress | null, summary: UploadSummaryState | null): number {
    if (summary) return 100
    if (!progress || progress.total <= 0) return 0

    const stageWeight =
        progress.stage === 'awaiting_confirmation'
            ? 0.2
            : progress.stage === 'uploading'
                ? 0.45
                : 0.85

    return Math.min(99, Math.max(1, Math.round(((progress.currentIndex - 1) + stageWeight) / progress.total * 100)))
}

function formatChunkLocator(chunk: DocumentDetailChunk): string {
    const parts: string[] = []
    if (chunk.section) parts.push(`章节：${chunk.section}`)
    if (chunk.article_no) parts.push(`条款：${chunk.article_no}`)

    if (typeof chunk.page_start === 'number') {
        if (typeof chunk.page_end === 'number' && chunk.page_end !== chunk.page_start) {
            parts.push(`页码：${chunk.page_start}-${chunk.page_end}`)
        } else {
            parts.push(`页码：${chunk.page_start}`)
        }
    }

    if (typeof chunk.start_pos === 'number' && typeof chunk.end_pos === 'number') {
        parts.push(`字符：${chunk.start_pos}-${chunk.end_pos}`)
    }

    return parts.join(' / ') || '无定位信息'
}

function StatusChip({ status }: { status: string }) {
    const config = STATUS_MAP[status] || { label: status || '未知', tone: 'neutral' as const }
    return <span className={`kb-status-chip ${config.tone}`}>{config.label}</span>
}

function ActionButton({
    onClick,
    title,
    loading,
    danger = false,
    children,
}: {
    onClick?: () => void
    title: string
    loading?: boolean
    danger?: boolean
    children: ReactNode
}) {
    return (
        <button
            type="button"
            className={`kb-icon-btn${danger ? ' danger' : ''}`}
            onClick={onClick}
            disabled={loading}
            aria-label={title}
            title={title}
        >
            {loading ? <span className="kb-icon-btn-spinner" /> : children}
        </button>
    )
}

function confirmOverwrite(fileName: string, existingDocument: DuplicateDocumentInfo): Promise<'overwrite' | 'skip'> {
    return new Promise((resolve) => {
        Modal.confirm({
            title: `知识库已有《${existingDocument.title || fileName}》`,
            content: (
                <div>
                    <p>当前上传文件与知识库中的文档内容一致。</p>
                    <p>覆盖后会重建原文和分块；放弃则跳过当前文件。</p>
                </div>
            ),
            okText: '覆盖',
            cancelText: '放弃上传',
            okButtonProps: { danger: true },
            onOk: () => resolve('overwrite'),
            onCancel: () => resolve('skip'),
        })
    })
}

export default function KnowledgePage() {
    const [docs, setDocs] = useState<DocItem[]>([])
    const [loading, setLoading] = useState(false)
    const [uploading, setUploading] = useState(false)
    const [uploadProgress, setUploadProgress] = useState<BatchImportProgress | null>(null)
    const [uploadSummary, setUploadSummary] = useState<UploadSummaryState | null>(null)
    const [detailOpen, setDetailOpen] = useState(false)
    const [detailLoading, setDetailLoading] = useState(false)
    const [detailDoc, setDetailDoc] = useState<DocumentDetail | null>(null)

    const fetchDocs = useCallback(async () => {
        setLoading(true)
        try {
            const result = await listDocuments()
            setDocs((result.items || []) as DocItem[])
        } catch (err: any) {
            message.error(`获取文档列表失败：${err?.message || '未知错误'}`)
        } finally {
            setLoading(false)
        }
    }, [])

    useEffect(() => {
        void fetchDocs()
    }, [fetchDocs])

    const openDetailDrawer = useCallback(async (docId: string) => {
        setDetailOpen(true)
        setDetailLoading(true)
        try {
            const detail = await getDocumentDetail(docId)
            setDetailDoc(detail)
        } catch (err: any) {
            setDetailDoc(null)
            message.error(`获取文档详情失败：${err?.message || '未知错误'}`)
            setDetailOpen(false)
        } finally {
            setDetailLoading(false)
        }
    }, [])

    const handleUploadBatch = useCallback(
        async (files: File[]) => {
            if (files.length === 0) return

            setUploading(true)
            setUploadProgress(null)
            setUploadSummary(null)
            try {
                const result = await importDocuments(files, {
                    onProgress: (progress) => {
                        setUploadProgress(progress)
                    },
                    onDuplicate: async ({ file, existingDocument }) => confirmOverwrite(file.name, existingDocument),
                })

                const failedFiles = result.items.filter((item) => !item.success && !item.skipped).map((item) => item.fileName)
                const skippedFiles = result.items.filter((item) => item.skipped).map((item) => item.fileName)
                const overwrittenCount = result.items.filter((item) => item.overwritten).length
                const summary: UploadSummaryState = {
                    total: result.total,
                    successCount: result.successCount,
                    failureCount: result.failureCount,
                    skippedCount: result.skippedCount,
                    overwrittenCount,
                    failedFiles,
                    skippedFiles,
                }
                setUploadSummary(summary)

                if (summary.failureCount === 0 && summary.skippedCount === 0) {
                    message.success(
                        `批量上传完成：成功 ${summary.successCount}/${summary.total}${summary.overwrittenCount > 0 ? `，覆盖 ${summary.overwrittenCount}` : ''}`
                    )
                } else if (summary.successCount === 0 && summary.failureCount > 0) {
                    message.error(
                        `批量上传失败：${failedFiles.slice(0, 3).join('、')}${failedFiles.length > 3 ? ' 等' : ''}`
                    )
                } else {
                    message.warning(
                        `批量上传完成：成功 ${summary.successCount}/${summary.total}，跳过 ${summary.skippedCount}，失败 ${summary.failureCount}`
                    )
                }

                await fetchDocs()
            } finally {
                setUploading(false)
                setUploadProgress(null)
            }
        },
        [fetchDocs]
    )

    const handleIndex = useCallback(
        async (docId: string) => {
            setDocs((prev) => prev.map((item) => (item.doc_id === docId ? { ...item, _loading: 'indexing' } : item)))
            try {
                await indexDocument(docId)
                message.success('索引完成')
                await fetchDocs()
            } catch (err: any) {
                message.error(`索引失败：${err?.message || '未知错误'}`)
                setDocs((prev) =>
                    prev.map((item) => (item.doc_id === docId ? { ...item, _loading: undefined } : item))
                )
            }
        },
        [fetchDocs]
    )

    const handleDelete = useCallback(
        async (docId: string) => {
            setDocs((prev) => prev.map((item) => (item.doc_id === docId ? { ...item, _loading: 'deleting' } : item)))
            try {
                await deleteDocument(docId)
                message.success('文档已删除')
                await fetchDocs()
            } catch (err: any) {
                message.error(`删除失败：${err?.message || '未知错误'}`)
                setDocs((prev) =>
                    prev.map((item) => (item.doc_id === docId ? { ...item, _loading: undefined } : item))
                )
            }
        },
        [fetchDocs]
    )

    const indexedCount = docs.filter((item) => item.parse_status === 'indexed').length
    const pendingCount = docs.filter((item) => item.parse_status !== 'indexed').length
    const totalChunks = docs.reduce((sum, item) => sum + (item.chunks || 0), 0)
    const uploadPercent = useMemo(
        () => buildUploadPercent(uploadProgress, uploadSummary),
        [uploadProgress, uploadSummary]
    )
    const currentStepLabel = uploadProgress ? resolveProgressStep(uploadProgress.stage) : ''

    const sidebarStatusText = useMemo(() => {
        if (uploadProgress) {
            return `${uploadProgress.currentIndex}/${uploadProgress.total} ${currentStepLabel}：${uploadProgress.fileName}`
        }
        if (uploadSummary) {
            if (uploadSummary.failureCount > 0 || uploadSummary.skippedCount > 0) {
                const firstSkipped = uploadSummary.skippedFiles[0]
                const firstFailed = uploadSummary.failedFiles[0]
                return `最近一批完成：成功 ${uploadSummary.successCount}，跳过 ${uploadSummary.skippedCount}，失败 ${uploadSummary.failureCount}${firstSkipped ? `；首个跳过：${firstSkipped}` : ''}${firstFailed ? `；首个失败：${firstFailed}` : ''}`
            }
            return `最近一批已处理完成：${uploadSummary.successCount} 份文档已入库${uploadSummary.overwrittenCount > 0 ? `，其中覆盖 ${uploadSummary.overwrittenCount} 份` : ''}`
        }
        if (docs.length === 0) {
            return '还没有文档，上传后会自动进入索引流程。'
        }
        if (pendingCount > 0) {
            return `${pendingCount} 份文档仍在等待索引或处理中。`
        }
        return '知识库已就绪，已完成分块的文档可直接点开查原文和分块详情。'
    }, [currentStepLabel, docs.length, pendingCount, uploadProgress, uploadSummary])

    const chunkColumns: ColumnsType<DocumentDetailChunk> = useMemo(
        () => [
            {
                title: '序号',
                dataIndex: 'chunk_index',
                key: 'chunk_index',
                width: 80,
                render: (value: number) => value + 1,
            },
            {
                title: '定位',
                key: 'locator',
                width: 240,
                render: (_: unknown, record: DocumentDetailChunk) => (
                    <div className="kb-detail-locator">{formatChunkLocator(record)}</div>
                ),
            },
            {
                title: '分块内容',
                dataIndex: 'chunk_text',
                key: 'chunk_text',
                render: (value: string) => <div className="kb-detail-chunk-text">{value || '暂无内容'}</div>,
            },
        ],
        []
    )

    const columns: ColumnsType<DocItem> = [
        {
            title: '文档',
            dataIndex: 'title',
            key: 'title',
            ellipsis: true,
            render: (title: string, record: DocItem) => {
                const canInspect = record.parse_status === 'indexed'
                return (
                    <div className="kb-doc-main">
                        <div className="kb-doc-title">
                            {canInspect ? (
                                <button
                                    type="button"
                                    className="kb-doc-link"
                                    onClick={() => void openDetailDrawer(record.doc_id)}
                                >
                                    {title}
                                </button>
                            ) : (
                                title
                            )}
                        </div>
                        <div className="kb-doc-subline">
                            <span className="kb-type-chip">{(record.doc_type || 'file').toUpperCase()}</span>
                            <span>{record.doc_id.slice(0, 8)}</span>
                        </div>
                    </div>
                )
            },
        },
        {
            title: '状态',
            dataIndex: 'parse_status',
            key: 'parse_status',
            width: 108,
            render: (status: string) => <StatusChip status={status} />,
        },
        {
            title: '分块',
            dataIndex: 'chunks',
            key: 'chunks',
            width: 88,
            align: 'center',
            render: (chunks: number) => <span className="kb-count-chip">{chunks || 0}</span>,
        },
        {
            title: '时间',
            dataIndex: 'created_at',
            key: 'created_at',
            width: 132,
            render: (time: string) => <span className="kb-time">{formatTime(time)}</span>,
        },
        {
            title: '',
            key: 'actions',
            width: 148,
            render: (_: unknown, record: DocItem) => (
                <div className="kb-row-actions">
                    {record.parse_status === 'indexed' && (
                        <ActionButton title="查看详情" onClick={() => void openDetailDrawer(record.doc_id)}>
                            <FileSearchOutlined />
                        </ActionButton>
                    )}

                    {record.parse_status !== 'indexed' && (
                        <ActionButton
                            title="建立索引"
                            loading={record._loading === 'indexing'}
                            onClick={() => void handleIndex(record.doc_id)}
                        >
                            <ThunderboltOutlined />
                        </ActionButton>
                    )}

                    <Popconfirm
                        title="删除文档"
                        description="删除后会清空该文档的原文和索引。"
                        onConfirm={() => void handleDelete(record.doc_id)}
                        okText="删除"
                        cancelText="取消"
                        okButtonProps={{ danger: true }}
                    >
                        <span>
                            <ActionButton title="删除文档" loading={record._loading === 'deleting'} danger>
                                <DeleteOutlined />
                            </ActionButton>
                        </span>
                    </Popconfirm>
                </div>
            ),
        },
    ]

    return (
        <div className="kb-page">
            <div className="kb-shell">
                <aside className="kb-sidebar">
                    <div className="kb-sidebar-header">
                        <div className="kb-sidebar-heading">
                            <span className="kb-sidebar-kicker">KNOWLEDGE CONSOLE</span>
                            <h1 className="kb-sidebar-title">知识库</h1>
                            <p className="kb-sidebar-subtitle">上传、索引、管理和查阅文档</p>
                        </div>
                        <Link href="/chat" className="kb-chat-link" prefetch={false}>
                            <MessageOutlined />
                            去对话
                        </Link>
                    </div>

                    <Dragger
                        accept=".pdf,.html,.htm,.txt,.docx"
                        multiple
                        showUploadList={false}
                        beforeUpload={(file, fileList) => {
                            const isLastFile = file.uid === fileList[fileList.length - 1]?.uid
                            if (isLastFile) {
                                void handleUploadBatch(fileList as File[])
                            }
                            return Upload.LIST_IGNORE
                        }}
                        disabled={uploading}
                        className="kb-upload-card"
                    >
                        <div className="kb-upload-inner">
                            <div className="kb-upload-icon">
                                <InboxOutlined />
                            </div>
                            <div className="kb-upload-copy">
                                <div className="kb-upload-title">
                                    {uploadProgress ? currentStepLabel : '拖入文档或点击批量上传'}
                                </div>
                                <div className="kb-upload-meta">
                                    {uploadProgress
                                        ? `${uploadProgress.currentIndex}/${uploadProgress.total} · ${uploadProgress.fileName}`
                                        : '支持多选，PDF / HTML / TXT / DOCX'}
                                </div>
                            </div>
                        </div>
                    </Dragger>

                    <div className="kb-status-strip">
                        <span className="kb-status-dot" />
                        <span>{sidebarStatusText}</span>
                    </div>

                    {(uploading || uploadSummary) && (
                        <Progress
                            percent={uploadPercent}
                            size="small"
                            className="kb-upload-progress"
                            status={
                                uploadSummary
                                    ? uploadSummary.failureCount > 0
                                        ? 'exception'
                                        : 'success'
                                    : 'active'
                            }
                        />
                    )}

                    <div className="kb-stat-grid">
                        <div className="kb-stat-card">
                            <span className="kb-stat-label">文档</span>
                            <span className="kb-stat-value">{docs.length}</span>
                        </div>
                        <div className="kb-stat-card">
                            <span className="kb-stat-label">已索引</span>
                            <span className="kb-stat-value">{indexedCount}</span>
                        </div>
                        <div className="kb-stat-card">
                            <span className="kb-stat-label">分块</span>
                            <span className="kb-stat-value">{totalChunks}</span>
                        </div>
                    </div>

                    <div className="kb-sidebar-note">
                        重复文档会先弹出覆盖确认；批量导入按顺序执行，单个文件失败或跳过都不会堵住后面的文件。
                    </div>
                </aside>

                <section className="kb-main">
                    <header className="kb-main-header">
                        <div className="kb-main-heading">
                            <span className="kb-main-kicker">LIBRARY OVERVIEW</span>
                            <h2 className="kb-main-title">文档列表</h2>
                            <p className="kb-main-meta">
                                {docs.length} 份文档 · {indexedCount} 份已索引 · {totalChunks} 个分块
                            </p>
                        </div>

                        <div className="kb-main-actions">
                            <Link href="/chat" className="kb-return-chat-btn" prefetch={false}>
                                <ArrowLeftOutlined />
                                返回咨询对话
                            </Link>

                            <button
                                type="button"
                                className="kb-refresh-btn"
                                onClick={() => void fetchDocs()}
                                disabled={loading}
                            >
                                <ReloadOutlined />
                                刷新
                            </button>
                        </div>
                    </header>

                    <div className="kb-table-wrap">
                        <Table
                            columns={columns}
                            dataSource={docs}
                            rowKey="doc_id"
                            loading={loading}
                            pagination={false}
                            size="middle"
                            locale={{
                                emptyText: (
                                    <div className="kb-empty-state">
                                        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="还没有知识库文档" />
                                        <p className="kb-empty-copy">
                                            上传法规、制度、案例摘要或内部材料后，对话页才能基于这些内容返回可引用的回答。
                                        </p>
                                        <Link href="/chat" className="kb-return-chat-btn inline" prefetch={false}>
                                            <ArrowLeftOutlined />
                                            返回咨询对话
                                        </Link>
                                    </div>
                                ),
                            }}
                        />
                    </div>
                </section>
            </div>

            <Drawer
                title={detailDoc?.title || '文档详情'}
                open={detailOpen}
                width={760}
                onClose={() => {
                    setDetailOpen(false)
                    setDetailDoc(null)
                }}
                extra={
                    detailDoc?.download_url ? (
                        <a
                            className="kb-detail-download"
                            href={resolveApiUrl(detailDoc.download_url)}
                            target="_blank"
                            rel="noreferrer"
                        >
                            <DownloadOutlined />
                            下载原文件
                        </a>
                    ) : null
                }
            >
                {detailLoading ? (
                    <div className="kb-detail-loading">
                        <Spin />
                    </div>
                ) : detailDoc ? (
                    <div className="kb-detail-shell">
                        <div className="kb-detail-summary">
                            <div>
                                <span className="kb-detail-label">文档类型</span>
                                <strong>{detailDoc.doc_type?.toUpperCase() || '-'}</strong>
                            </div>
                            <div>
                                <span className="kb-detail-label">分块数量</span>
                                <strong>{detailDoc.chunk_items.length}</strong>
                            </div>
                            <div>
                                <span className="kb-detail-label">原始文件</span>
                                <strong>{detailDoc.original_file_name || '未记录'}</strong>
                            </div>
                            <div>
                                <span className="kb-detail-label">导入时间</span>
                                <strong>{formatTime(detailDoc.created_at)}</strong>
                            </div>
                        </div>

                        <Tabs
                            items={[
                                {
                                    key: 'text',
                                    label: '原文内容',
                                    children: (
                                        <div className="kb-detail-text-wrap">
                                            <pre className="kb-detail-text">{detailDoc.text || '暂无原文内容'}</pre>
                                        </div>
                                    ),
                                },
                                {
                                    key: 'chunks',
                                    label: '分块详情',
                                    children: (
                                        <Table
                                            columns={chunkColumns}
                                            dataSource={detailDoc.chunk_items}
                                            rowKey={(record) => record.chunk_id || `${record.chunk_index}`}
                                            pagination={{ pageSize: 6, hideOnSinglePage: true }}
                                            size="small"
                                        />
                                    ),
                                },
                            ]}
                        />
                    </div>
                ) : (
                    <Empty description="暂无文档详情" />
                )}
            </Drawer>
        </div>
    )
}
