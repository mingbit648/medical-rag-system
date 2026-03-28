'use client'

import Link from 'next/link'
import {
    Button,
    Drawer,
    Empty,
    Form,
    Input,
    Modal,
    Popconfirm,
    Select,
    Space,
    Spin,
    Table,
    Tag,
    Typography,
    Upload,
    message,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useCallback, useEffect, useMemo, useState } from 'react'
import {
    ArrowLeftOutlined,
    DeleteOutlined,
    DownloadOutlined,
    InboxOutlined,
    PlusOutlined,
    ReloadOutlined,
    UploadOutlined,
} from '@ant-design/icons'
import AuthGuard from '@/components/AuthGuard'
import { resolveApiUrl } from '@/lib/api/client'
import {
    createKnowledgeBase,
    deleteDocument,
    deleteKnowledgeBase,
    getDocumentDetail,
    importDocuments,
    indexDocument,
    listDocuments,
    updateKnowledgeBase,
    type DocStatusResult,
    type DocumentDetail,
} from '@/lib/api/legalRag'
import { useAppSession } from '@/lib/session/AppSessionProvider'


const { Dragger } = Upload


interface DocRow extends DocStatusResult {
    _loading?: 'indexing' | 'deleting'
}


function KnowledgeWorkspace() {
    const {
        knowledgeBases,
        currentKnowledgeBase,
        currentKnowledgeBaseId,
        selectKnowledgeBase,
        refreshKnowledgeBases,
    } = useAppSession()
    const [docs, setDocs] = useState<DocRow[]>([])
    const [loading, setLoading] = useState(false)
    const [uploading, setUploading] = useState(false)
    const [detailOpen, setDetailOpen] = useState(false)
    const [detailLoading, setDetailLoading] = useState(false)
    const [detailDoc, setDetailDoc] = useState<DocumentDetail | null>(null)
    const [createOpen, setCreateOpen] = useState(false)
    const [renameOpen, setRenameOpen] = useState(false)
    const [createForm] = Form.useForm()
    const [renameForm] = Form.useForm()

    const writable = currentKnowledgeBase?.access_level === 'write'
    const isPrivateKb = currentKnowledgeBase?.visibility === 'private'

    const fetchDocs = useCallback(async () => {
        if (!currentKnowledgeBaseId) {
            setDocs([])
            return
        }
        setLoading(true)
        try {
            const result = await listDocuments(currentKnowledgeBaseId)
            setDocs((result.items || []) as DocRow[])
        } catch (err: any) {
            message.error(err?.message || '加载文档列表失败')
        } finally {
            setLoading(false)
        }
    }, [currentKnowledgeBaseId])

    useEffect(() => {
        void fetchDocs()
    }, [fetchDocs])

    useEffect(() => {
        renameForm.setFieldsValue({ name: currentKnowledgeBase?.name || '', description: currentKnowledgeBase?.description || '' })
    }, [currentKnowledgeBase?.description, currentKnowledgeBase?.name, renameForm])

    const openDetailDrawer = useCallback(async (docId: string) => {
        setDetailOpen(true)
        setDetailLoading(true)
        try {
            setDetailDoc(await getDocumentDetail(docId))
        } catch (err: any) {
            setDetailOpen(false)
            message.error(err?.message || '加载文档详情失败')
        } finally {
            setDetailLoading(false)
        }
    }, [])

    async function handleUpload(files: File[]) {
        if (!currentKnowledgeBaseId || !writable || files.length === 0) return
        setUploading(true)
        try {
            const result = await importDocuments(files, { kbId: currentKnowledgeBaseId })
            const summary = `成功 ${result.successCount}，跳过 ${result.skippedCount}，失败 ${result.failureCount}`
            if (result.failureCount > 0) {
                message.warning(`导入完成：${summary}`)
            } else {
                message.success(`导入完成：${summary}`)
            }
            await fetchDocs()
        } catch (err: any) {
            message.error(err?.message || '导入文档失败')
        } finally {
            setUploading(false)
        }
    }

    async function handleIndex(docId: string) {
        setDocs((prev) => prev.map((item) => (item.doc_id === docId ? { ...item, _loading: 'indexing' } : item)))
        try {
            await indexDocument(docId)
            message.success('索引任务已入队')
            await fetchDocs()
        } catch (err: any) {
            message.error(err?.message || '索引失败')
            setDocs((prev) => prev.map((item) => (item.doc_id === docId ? { ...item, _loading: undefined } : item)))
        }
    }

    async function handleDeleteDocument(docId: string) {
        setDocs((prev) => prev.map((item) => (item.doc_id === docId ? { ...item, _loading: 'deleting' } : item)))
        try {
            await deleteDocument(docId)
            message.success('文档已删除')
            await fetchDocs()
        } catch (err: any) {
            message.error(err?.message || '删除文档失败')
            setDocs((prev) => prev.map((item) => (item.doc_id === docId ? { ...item, _loading: undefined } : item)))
        }
    }

    async function handleCreateKb(values: { name: string; description?: string }) {
        try {
            const created = await createKnowledgeBase(values)
            setCreateOpen(false)
            createForm.resetFields()
            await refreshKnowledgeBases(created.kb_id)
            message.success('知识库已创建')
        } catch (err: any) {
            message.error(err?.message || '创建知识库失败')
        }
    }

    async function handleRenameKb(values: { name: string; description?: string }) {
        if (!currentKnowledgeBaseId) return
        try {
            await updateKnowledgeBase(currentKnowledgeBaseId, values)
            setRenameOpen(false)
            await refreshKnowledgeBases(currentKnowledgeBaseId)
            message.success('知识库已更新')
        } catch (err: any) {
            message.error(err?.message || '更新知识库失败')
        }
    }

    async function handleDeleteKb() {
        if (!currentKnowledgeBaseId) return
        try {
            await deleteKnowledgeBase(currentKnowledgeBaseId)
            await refreshKnowledgeBases()
            message.success('知识库已删除')
        } catch (err: any) {
            message.error(err?.message || '删除知识库失败')
        }
    }

    const columns: ColumnsType<DocRow> = useMemo(
        () => [
            {
                title: '文档',
                dataIndex: 'title',
                key: 'title',
                render: (value: string, record) => (
                    <Button type="link" style={{ padding: 0 }} onClick={() => void openDetailDrawer(record.doc_id)}>
                        {value}
                    </Button>
                ),
            },
            {
                title: '状态',
                dataIndex: 'parse_status',
                key: 'parse_status',
                width: 120,
                render: (status: string) => {
                    const color = status === 'indexed' ? 'green' : status === 'failed' ? 'red' : status === 'indexing' ? 'blue' : 'gold'
                    return <Tag color={color}>{status}</Tag>
                },
            },
            {
                title: '分块',
                dataIndex: 'chunks',
                key: 'chunks',
                width: 96,
            },
            {
                title: '导入时间',
                dataIndex: 'created_at',
                key: 'created_at',
                width: 180,
                render: (value: string) => new Date(value).toLocaleString('zh-CN'),
            },
            {
                title: '操作',
                key: 'actions',
                width: 220,
                render: (_: unknown, record) => (
                    <Space>
                        {writable && record.parse_status !== 'indexed' ? (
                            <Button
                                disabled={record.parse_status === 'indexing'}
                                loading={record._loading === 'indexing'}
                                onClick={() => void handleIndex(record.doc_id)}
                            >
                                {record.parse_status === 'indexing' ? '索引中' : '建索引'}
                            </Button>
                        ) : null}
                        {writable ? (
                            <Popconfirm
                                title="删除文档"
                                description="删除后会同时清理原文和索引。"
                                onConfirm={() => void handleDeleteDocument(record.doc_id)}
                            >
                                <Button danger loading={record._loading === 'deleting'} icon={<DeleteOutlined />}>
                                    删除
                                </Button>
                            </Popconfirm>
                        ) : null}
                    </Space>
                ),
            },
        ],
        [openDetailDrawer, writable]
    )

    return (
        <div style={{ minHeight: '100vh', background: '#f7f7f5', padding: 24 }}>
            <Space direction="vertical" size={16} style={{ width: '100%' }}>
                <Space style={{ width: '100%', justifyContent: 'space-between' }}>
                    <div>
                        <Typography.Title level={3} style={{ marginBottom: 4 }}>
                            知识库管理
                        </Typography.Title>
                        <Typography.Text type="secondary">
                            私有知识库可读写，系统知识库普通用户只读。
                        </Typography.Text>
                    </div>
                    <Space>
                        <Link href="/chat">
                            <Button icon={<ArrowLeftOutlined />}>返回聊天</Button>
                        </Link>
                        <Button icon={<ReloadOutlined />} onClick={() => void fetchDocs()} loading={loading}>
                            刷新
                        </Button>
                    </Space>
                </Space>

                <Space wrap>
                    <Select
                        style={{ minWidth: 280 }}
                        value={currentKnowledgeBaseId || undefined}
                        onChange={selectKnowledgeBase}
                        options={knowledgeBases.map((kb) => ({
                            value: kb.kb_id,
                            label: `${kb.name}${kb.visibility === 'system' ? '（系统）' : ''}`,
                        }))}
                    />
                    <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>
                        新建私有知识库
                    </Button>
                    {currentKnowledgeBase ? (
                        <Button onClick={() => setRenameOpen(true)} disabled={!writable}>
                            重命名
                        </Button>
                    ) : null}
                    {currentKnowledgeBase && isPrivateKb ? (
                        <Popconfirm
                            title="删除知识库"
                            description="只允许删除空私有知识库，且不能删掉最后一个私库。"
                            onConfirm={() => void handleDeleteKb()}
                        >
                            <Button danger disabled={!writable}>
                                删除知识库
                            </Button>
                        </Popconfirm>
                    ) : null}
                </Space>

                <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
                    当前知识库：
                    <Typography.Text strong>{currentKnowledgeBase?.name || '未选择'}</Typography.Text>
                    {currentKnowledgeBase?.visibility === 'system' ? '，系统共享' : '，用户私有'}
                    {writable ? '，可写' : '，只读'}
                </Typography.Paragraph>

                {writable ? (
                    <Dragger
                        accept=".pdf,.html,.htm,.txt,.docx"
                        multiple
                        showUploadList={false}
                        beforeUpload={(file, fileList) => {
                            const isLastFile = file.uid === fileList[fileList.length - 1]?.uid
                            if (isLastFile) {
                                void handleUpload(fileList as File[])
                            }
                            return Upload.LIST_IGNORE
                        }}
                        disabled={uploading || !currentKnowledgeBaseId}
                    >
                        <p className="ant-upload-drag-icon">
                            <InboxOutlined />
                        </p>
                        <p className="ant-upload-text">拖入文档或点击上传到当前知识库</p>
                        <p className="ant-upload-hint">上传完成后会自动提交索引任务。</p>
                    </Dragger>
                ) : (
                    <Empty description="当前知识库为只读，普通用户不能上传或删除文档。" />
                )}

                <Table
                    rowKey="doc_id"
                    columns={columns}
                    dataSource={docs}
                    loading={loading}
                    locale={{ emptyText: <Empty description="当前知识库没有文档" /> }}
                    pagination={{ pageSize: 8, hideOnSinglePage: true }}
                />
            </Space>

            <Drawer
                title={detailDoc?.title || '文档详情'}
                open={detailOpen}
                width={720}
                onClose={() => {
                    setDetailOpen(false)
                    setDetailDoc(null)
                }}
                extra={
                    detailDoc?.download_url ? (
                        <a href={resolveApiUrl(detailDoc.download_url)} target="_blank" rel="noreferrer">
                            <Button icon={<DownloadOutlined />}>打开原文</Button>
                        </a>
                    ) : null
                }
            >
                {detailLoading ? (
                    <div style={{ minHeight: 240, display: 'grid', placeItems: 'center' }}>
                        <Spin />
                    </div>
                ) : detailDoc ? (
                    <Space direction="vertical" size={16} style={{ width: '100%' }}>
                        <Typography.Paragraph>
                            类型：{detailDoc.doc_type.toUpperCase()}，分块：{detailDoc.chunk_items.length}
                        </Typography.Paragraph>
                        <div style={{ maxHeight: '60vh', overflow: 'auto', background: '#fafafa', padding: 16, borderRadius: 8 }}>
                            <pre style={{ whiteSpace: 'pre-wrap', margin: 0 }}>{detailDoc.text || '暂无内容'}</pre>
                        </div>
                    </Space>
                ) : (
                    <Empty description="暂无文档详情" />
                )}
            </Drawer>

            <Modal
                title="新建私有知识库"
                open={createOpen}
                onCancel={() => setCreateOpen(false)}
                footer={null}
                destroyOnHidden
            >
                <Form form={createForm} layout="vertical" onFinish={handleCreateKb}>
                    <Form.Item name="name" label="名称" rules={[{ required: true, message: '请输入名称' }]}>
                        <Input />
                    </Form.Item>
                    <Form.Item name="description" label="描述">
                        <Input.TextArea rows={3} />
                    </Form.Item>
                    <Space style={{ width: '100%', justifyContent: 'flex-end' }}>
                        <Button onClick={() => setCreateOpen(false)}>取消</Button>
                        <Button type="primary" htmlType="submit" icon={<UploadOutlined />}>
                            创建
                        </Button>
                    </Space>
                </Form>
            </Modal>

            <Modal
                title="编辑知识库"
                open={renameOpen}
                onCancel={() => setRenameOpen(false)}
                footer={null}
                destroyOnHidden
            >
                <Form form={renameForm} layout="vertical" onFinish={handleRenameKb}>
                    <Form.Item name="name" label="名称" rules={[{ required: true, message: '请输入名称' }]}>
                        <Input />
                    </Form.Item>
                    <Form.Item name="description" label="描述">
                        <Input.TextArea rows={3} />
                    </Form.Item>
                    <Space style={{ width: '100%', justifyContent: 'flex-end' }}>
                        <Button onClick={() => setRenameOpen(false)}>取消</Button>
                        <Button type="primary" htmlType="submit">
                            保存
                        </Button>
                    </Space>
                </Form>
            </Modal>
        </div>
    )
}


export default function KnowledgePage() {
    return (
        <AuthGuard>
            <KnowledgeWorkspace />
        </AuthGuard>
    )
}
