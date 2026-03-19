'use client'

import { useCallback, useEffect, useState, type ReactNode } from 'react'
import Link from 'next/link'
import { Empty, Popconfirm, Table, Upload, message } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import {
    ArrowLeftOutlined,
    DeleteOutlined,
    InboxOutlined,
    MessageOutlined,
    ReloadOutlined,
    ThunderboltOutlined,
} from '@ant-design/icons'
import {
    deleteDocument,
    importDocuments,
    indexDocument,
    listDocuments,
    type BatchImportProgress,
    type DocStatusResult,
} from '@/lib/api/legalRag'

const { Dragger } = Upload

interface DocItem extends DocStatusResult {
    _loading?: 'indexing' | 'deleting'
}

interface UploadProgressState extends BatchImportProgress {
    step: string
}

interface UploadSummaryState {
    total: number
    successCount: number
    failureCount: number
    failedFiles: string[]
}

const STATUS_MAP: Record<string, { label: string; tone: 'neutral' | 'success' | 'danger' }> = {
    uploaded: { label: '待索引', tone: 'neutral' },
    indexed: { label: '已就绪', tone: 'success' },
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

export default function KnowledgePage() {
    const [docs, setDocs] = useState<DocItem[]>([])
    const [loading, setLoading] = useState(false)
    const [uploading, setUploading] = useState(false)
    const [uploadProgress, setUploadProgress] = useState<UploadProgressState | null>(null)
    const [uploadSummary, setUploadSummary] = useState<UploadSummaryState | null>(null)

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

    const handleUploadBatch = useCallback(
        async (files: File[]) => {
            if (files.length === 0) return

            setUploading(true)
            setUploadSummary(null)
            try {
                const result = await importDocuments(files, {
                    onProgress: (progress) => {
                        setUploadProgress({
                            ...progress,
                            step: progress.stage === 'uploading' ? '上传中' : '建立索引中',
                        })
                    },
                })
                const failedFiles = result.items.filter((item) => !item.success).map((item) => item.fileName)
                const summary: UploadSummaryState = {
                    total: result.total,
                    successCount: result.successCount,
                    failureCount: result.failureCount,
                    failedFiles,
                }
                setUploadSummary(summary)

                if (summary.failureCount === 0) {
                    const importedTitles = result.items
                        .filter((item) => item.success)
                        .map((item) => item.title)
                        .filter((title): title is string => Boolean(title))
                    const titlePreview = importedTitles[0]
                    const suffix = summary.total > 1 ? ` 等 ${summary.total} 份文档` : ''
                    message.success(titlePreview ? `《${titlePreview}》${suffix}已完成导入并建立索引` : `已完成 ${summary.total} 份文档导入`)
                } else if (summary.successCount === 0) {
                    message.error(`批量上传失败：${failedFiles.slice(0, 3).join('、')}${failedFiles.length > 3 ? ' 等' : ''}`)
                } else {
                    message.warning(
                        `批量上传完成，成功 ${summary.successCount} / ${summary.total}，失败 ${summary.failureCount}`
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
                void fetchDocs()
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
                void fetchDocs()
            } catch (err: any) {
                message.error(`删除失败：${err?.message || '未知错误'}`)
                setDocs((prev) =>
                    prev.map((item) => (item.doc_id === docId ? { ...item, _loading: undefined } : item))
                )
            }
        },
        [fetchDocs]
    )

    const columns: ColumnsType<DocItem> = [
        {
            title: '文档',
            dataIndex: 'title',
            key: 'title',
            ellipsis: true,
            render: (title: string, record: DocItem) => (
                <div className="kb-doc-main">
                    <div className="kb-doc-title">{title}</div>
                    <div className="kb-doc-subline">
                        <span className="kb-type-chip">{(record.doc_type || 'file').toUpperCase()}</span>
                        <span>{record.doc_id.slice(0, 8)}</span>
                    </div>
                </div>
            ),
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
            width: 104,
            render: (_: unknown, record: DocItem) => (
                <div className="kb-row-actions">
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
                        description="删除后会清空该文档相关索引。"
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

    const indexedCount = docs.filter((item) => item.parse_status === 'indexed').length
    const pendingCount = docs.filter((item) => item.parse_status !== 'indexed').length
    const totalChunks = docs.reduce((sum, item) => sum + (item.chunks || 0), 0)
    const sidebarStatusText = uploadProgress
        ? `${uploadProgress.currentIndex}/${uploadProgress.total} · ${uploadProgress.step} · ${uploadProgress.fileName}`
        : uploadSummary
            ? uploadSummary.failureCount > 0
                ? `最近一批完成：成功 ${uploadSummary.successCount}，失败 ${uploadSummary.failureCount}。${uploadSummary.failedFiles[0] ? ` 首个失败文件：${uploadSummary.failedFiles[0]}` : ''}`
                : `最近一批已处理完成：${uploadSummary.successCount} 份文档已入库。`
        : docs.length === 0
            ? '还没有文档，上传后会自动进入索引流程。'
            : pendingCount > 0
                ? `${pendingCount} 份文档正在等待索引或处理。`
                : '知识库已就绪，可以返回聊天页开始提问。'

    return (
        <div className="kb-page">
            <div className="kb-shell">
                <aside className="kb-sidebar">
                    <div className="kb-sidebar-header">
                        <div className="kb-sidebar-heading">
                            <span className="kb-sidebar-kicker">KNOWLEDGE CONSOLE</span>
                            <h1 className="kb-sidebar-title">知识库</h1>
                            <p className="kb-sidebar-subtitle">上传、索引、管理文档</p>
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
                            {uploadProgress ? (
                                <div className="kb-upload-copy">
                                    <div className="kb-upload-title">{uploadProgress.step}</div>
                                    <div className="kb-upload-meta">
                                        {uploadProgress.currentIndex}/{uploadProgress.total} · {uploadProgress.fileName}
                                    </div>
                                </div>
                            ) : (
                                <div className="kb-upload-copy">
                                    <div className="kb-upload-title">拖入文件或点击批量上传</div>
                                    <div className="kb-upload-meta">支持多选，PDF / HTML / TXT / DOCX</div>
                                </div>
                            )}
                        </div>
                    </Dragger>

                    <div className="kb-status-strip">
                        <span className="kb-status-dot" />
                        <span>{sidebarStatusText}</span>
                    </div>

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
                        文档上传后会按顺序自动进入索引流程。批量导入失败的文件不会阻塞剩余文件处理。
                    </div>
                </aside>

                <section className="kb-main">
                    <header className="kb-main-header">
                        <div className="kb-main-heading">
                            <span className="kb-main-kicker">LIBRARY OVERVIEW</span>
                            <h2 className="kb-main-title">文档列表</h2>
                            <p className="kb-main-meta">
                                {docs.length} 份文档 · {indexedCount} 份已索引 · {totalChunks} 个切片
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
                                        <Empty
                                            image={Empty.PRESENTED_IMAGE_SIMPLE}
                                            description="还没有知识库文档"
                                        />
                                        <p className="kb-empty-copy">
                                            上传法规、制度、案例摘要或内部材料后，聊天页就能基于这些内容给出可引用的回答。
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
        </div>
    )
}
