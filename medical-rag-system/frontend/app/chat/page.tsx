'use client'

import { useState, useRef, useCallback, useMemo, useEffect } from 'react'
import { Button, Input, Upload, message, Tooltip, Tag, Drawer, Empty, Spin, Collapse } from 'antd'
import {
    SendOutlined,
    PaperClipOutlined,
    FileTextOutlined,
    InfoCircleOutlined,
    HighlightOutlined,
    ClearOutlined,
    BugOutlined,
    SafetyCertificateOutlined,
    DatabaseOutlined,
} from '@ant-design/icons'
import MarkdownIt from 'markdown-it'
import {
    chatCompletionStream,
    importDocument,
    indexDocument,
    getDocumentStatus,
    getCitationView,
    type CitationItem,
    type CitationViewData,
} from '@/lib/api/legalRag'

const { TextArea } = Input

const md = new MarkdownIt({ html: false, linkify: true, typographer: true })

const QUICK_PROMPTS = [
    '公司拖欠工资时，劳动者应先收集哪些证据？',
    '劳动合同到期不续签，经济补偿应如何计算？',
    '被违法辞退后，申请劳动仲裁通常需要哪些材料？',
]

const WORKFLOW_NOTES = [
    '先上传 PDF、HTML、TXT 或 DOCX，系统会建立可检索索引。',
    '回答会附上引用来源与命中文本，便于快速核对依据。',
    '当前界面仅用于辅助检索与学习，不替代律师意见。',
]

const timeFormatter = new Intl.DateTimeFormat('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
})

interface ChatMessage {
    id: string
    role: 'user' | 'assistant'
    content: string
    citations?: CitationItem[]
    timestamp: number
}

interface HighlightPieces {
    before: string
    hit: string
    after: string
}

function toHighlightPieces(view: CitationViewData | null): HighlightPieces | null {
    if (!view) return null
    if (
        view.highlight.method === 'offset' &&
        typeof view.highlight.start === 'number' &&
        typeof view.highlight.end === 'number'
    ) {
        const start = Math.max(0, Math.min(view.highlight.start, view.context_text.length))
        const end = Math.max(start, Math.min(view.highlight.end, view.context_text.length))
        return {
            before: view.context_text.slice(0, start),
            hit: view.context_text.slice(start, end),
            after: view.context_text.slice(end),
        }
    }
    if (view.highlight.method === 'whole_chunk' && view.highlight.chunk_text) {
        return { before: '', hit: view.highlight.chunk_text, after: '' }
    }
    return { before: '', hit: view.context_text, after: '' }
}

function formatMessageTime(timestamp: number): string {
    return timeFormatter.format(new Date(timestamp))
}

export default function ChatPage() {
    const [messages, setMessages] = useState<ChatMessage[]>([])
    const [inputValue, setInputValue] = useState('')
    const [sessionId, setSessionId] = useState('')
    const [streaming, setStreaming] = useState(false)
    const [docId, setDocId] = useState('')
    const [indexing, setIndexing] = useState(false)
    const [indexStatus, setIndexStatus] = useState('')
    const [citationDrawerOpen, setCitationDrawerOpen] = useState(false)
    const [viewingCitation, setViewingCitation] = useState<CitationViewData | null>(null)
    const [viewingCitationLoading, setViewingCitationLoading] = useState(false)

    const bottomRef = useRef<HTMLDivElement>(null)
    const highlightRef = useRef<HTMLElement>(null)

    useEffect(() => {
        if (viewingCitation && !viewingCitationLoading && highlightRef.current) {
            window.setTimeout(() => {
                highlightRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' })
            }, 100)
        }
    }, [viewingCitation, viewingCitationLoading])

    const scrollToBottom = useCallback(() => {
        window.setTimeout(() => {
            bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
        }, 50)
    }, [])

    const handleSend = useCallback(async () => {
        const query = inputValue.trim()
        if (!query || streaming) return

        const now = Date.now()
        const assistantId = `assistant_${now}`

        setMessages((prev) => [
            ...prev,
            {
                id: `user_${now}`,
                role: 'user',
                content: query,
                timestamp: now,
            },
            {
                id: assistantId,
                role: 'assistant',
                content: '',
                timestamp: now + 1,
            },
        ])
        setInputValue('')
        setStreaming(true)
        scrollToBottom()

        try {
            await chatCompletionStream(
                { session_id: sessionId || undefined, query },
                {
                    onToken: (token) => {
                        setMessages((prev) =>
                            prev.map((item) =>
                                item.id === assistantId ? { ...item, content: item.content + token } : item
                            )
                        )
                        scrollToBottom()
                    },
                    onDone: (payload) => {
                        setSessionId(payload.session_id)
                        setMessages((prev) =>
                            prev.map((item) =>
                                item.id === assistantId
                                    ? { ...item, citations: payload.citations }
                                    : item
                            )
                        )
                        scrollToBottom()
                    },
                    onError: (errMsg) => {
                        setMessages((prev) =>
                            prev.map((item) =>
                                item.id === assistantId
                                    ? { ...item, content: item.content || `生成失败：${errMsg}` }
                                    : item
                            )
                        )
                    },
                }
            )
        } catch (err: any) {
            setMessages((prev) =>
                prev.map((item) =>
                    item.id === assistantId
                        ? { ...item, content: `请求失败：${err?.message || '未知错误'}` }
                        : item
                )
            )
        } finally {
            setStreaming(false)
        }
    }, [inputValue, scrollToBottom, sessionId, streaming])

    const handleFileUpload = useCallback(async (file: File) => {
        setIndexing(true)
        setIndexStatus('正在导入文档...')

        try {
            const imported = await importDocument(file)
            setDocId(imported.doc_id)
            setIndexStatus('正在建立检索索引...')
            await indexDocument(imported.doc_id)
            const status = await getDocumentStatus(imported.doc_id)
            setIndexStatus(`已接入《${status.title}》 · ${status.chunks} 个分块`)
            message.success(`文档《${status.title}》已导入并完成索引`)
        } catch (err: any) {
            const detail = err?.message || '文档处理失败'
            setIndexStatus(`处理失败：${detail}`)
            message.error(detail)
        } finally {
            setIndexing(false)
        }

        return false
    }, [])

    const handleViewCitation = useCallback(async (citationId: string) => {
        setCitationDrawerOpen(true)
        setViewingCitation(null)
        setViewingCitationLoading(true)

        try {
            const data = await getCitationView(citationId)
            setViewingCitation(data)
        } catch (err: any) {
            message.error(`查看引用失败：${err?.message || '未知错误'}`)
        } finally {
            setViewingCitationLoading(false)
        }
    }, [])

    const handleClearChat = useCallback(() => {
        setMessages([])
        setSessionId('')
    }, [])

    const highlightPieces = useMemo(() => toHighlightPieces(viewingCitation), [viewingCitation])
    const statusSummary = indexing
        ? '正在接入资料并重建索引。'
        : indexStatus || (docId ? '文档已接入，可继续追问并查看引用。' : '先上传资料，再发起问题。')
    const activeDocumentLabel = docId ? `${docId.slice(0, 8)}...` : '未接入'

    return (
        <div className="chat-page">
            <div className="chat-shell">
                <header className="chat-header">
                    <div className="chat-brand">
                        <div className="chat-brand-mark">
                            <FileTextOutlined style={{ fontSize: 24 }} />
                        </div>
                        <div className="chat-header-copy">
                            <div className="chat-header-kicker">Labor Dispute Dossier</div>
                            <h1 className="chat-header-title">法律辅助咨询工作台</h1>
                            <p className="chat-header-subtitle">
                                面向劳动争议场景的检索增强问答界面。你可以上传法规、裁判文书或业务资料，系统将返回带引用依据的答案。
                            </p>
                        </div>
                    </div>
                    <div className="chat-toolbar">
                        <div className="chat-status-pill">
                            <DatabaseOutlined />
                            {docId ? '已接入资料' : '等待导入文档'}
                        </div>
                        <Upload
                            accept=".pdf,.html,.htm,.txt,.docx"
                            showUploadList={false}
                            beforeUpload={(file) => {
                                void handleFileUpload(file)
                                return false
                            }}
                            disabled={indexing}
                        >
                            <Button icon={<PaperClipOutlined />} loading={indexing}>
                                {indexing ? '处理中' : '上传文档'}
                            </Button>
                        </Upload>
                        <Tooltip title="清空当前对话">
                            <Button icon={<ClearOutlined />} onClick={handleClearChat} disabled={streaming} />
                        </Tooltip>
                    </div>
                </header>

                <div className="chat-stage">
                    <aside className="chat-sidebar">
                        <section className="dossier-card">
                            <p className="dossier-eyebrow">Case Board</p>
                            <h2 className="dossier-title">证据先行，答案可回溯。</h2>
                            <p className="dossier-copy">
                                当前界面把法律问答包装成一份可核对的案卷。先导入资料，再逐步追问，最后打开引用核对命中文本。
                            </p>
                            <div className="dossier-grid">
                                <div className="dossier-stat">
                                    <span className="dossier-stat-label">当前文档</span>
                                    <span className="dossier-stat-value">{activeDocumentLabel}</span>
                                </div>
                                <div className="dossier-stat">
                                    <span className="dossier-stat-label">会话状态</span>
                                    <span className="dossier-stat-value">{streaming ? '生成中' : '待提问'}</span>
                                </div>
                            </div>
                        </section>

                        <section className="dossier-card">
                            <p className="dossier-eyebrow">Workflow</p>
                            <ul className="dossier-list">
                                {WORKFLOW_NOTES.map((note) => (
                                    <li key={note}>{note}</li>
                                ))}
                            </ul>
                        </section>

                        <section className="dossier-card">
                            <p className="dossier-eyebrow">Quick Prompts</p>
                            <div className="prompt-grid">
                                {QUICK_PROMPTS.map((prompt) => (
                                    <button
                                        key={prompt}
                                        type="button"
                                        className="prompt-chip"
                                        onClick={() => setInputValue(prompt)}
                                    >
                                        {prompt}
                                    </button>
                                ))}
                            </div>
                        </section>
                    </aside>

                    <section className="chat-main">
                        <main className="chat-messages">
                            <div className="chat-thread">
                                {messages.length === 0 && (
                                    <section className="chat-welcome">
                                        <div className="chat-welcome-top">
                                            <div>
                                                <div className="chat-welcome-icon">
                                                    <SafetyCertificateOutlined />
                                                </div>
                                                <h2 className="chat-welcome-title">把每一次回答都当作可复核的案卷记录。</h2>
                                                <p className="chat-welcome-copy">
                                                    上传法律文本后，系统会通过混合检索与重排序生成回答，并在每个结论后附上命中的引用来源，方便你快速核对依据。
                                                </p>
                                            </div>
                                            <div className="chat-welcome-disclaimer">
                                                <InfoCircleOutlined />
                                                仅用于学习、整理与辅助检索，不构成正式法律意见。
                                            </div>
                                        </div>
                                        <div className="chat-welcome-panels">
                                            <div className="chat-welcome-panel">
                                                <h3>建议提问方式</h3>
                                                <p>用事实加问题的格式输入，例如“公司连续两个月拖欠工资，我想申请仲裁，需要准备哪些证据？”</p>
                                            </div>
                                            <div className="chat-welcome-panel">
                                                <h3>推荐操作顺序</h3>
                                                <div className="chat-welcome-hints">
                                                    {QUICK_PROMPTS.map((prompt) => (
                                                        <button
                                                            key={prompt}
                                                            type="button"
                                                            className="chat-hint"
                                                            onClick={() => setInputValue(prompt)}
                                                        >
                                                            {prompt}
                                                        </button>
                                                    ))}
                                                </div>
                                            </div>
                                        </div>
                                    </section>
                                )}

                                {messages.map((msg) => (
                                    <div key={msg.id} className={`chat-bubble-row ${msg.role}`}>
                                        <div className="chat-message-stack">
                                            <div className="chat-message-meta">
                                                <span className="chat-message-role">
                                                    <FileTextOutlined />
                                                    {msg.role === 'assistant' ? '分析答复' : '提问记录'}
                                                </span>
                                                <span className="chat-message-time">{formatMessageTime(msg.timestamp)}</span>
                                            </div>
                                            <div className={`chat-bubble ${msg.role}`}>
                                                {msg.role === 'assistant' ? (
                                                    <>
                                                        {msg.content ? (
                                                            <div
                                                                className="chat-markdown"
                                                                dangerouslySetInnerHTML={{ __html: md.render(msg.content) }}
                                                            />
                                                        ) : (
                                                            <Spin size="small" />
                                                        )}
                                                        {msg.citations && msg.citations.length > 0 && (
                                                            <div className="chat-citations">
                                                                <div className="chat-citations-header">
                                                                    <FileTextOutlined />
                                                                    引用来源 {msg.citations.length} 条
                                                                </div>
                                                                {msg.citations.map((citation, index) => (
                                                                    <div key={citation.citation_id} className="chat-citation-item">
                                                                        <div className="chat-citation-idx">[{index + 1}]</div>
                                                                        <div className="chat-citation-body">
                                                                            <div className="chat-citation-title">{citation.source.title}</div>
                                                                            <div className="chat-citation-snippet">{citation.snippet}</div>
                                                                            <div className="chat-citation-tags">
                                                                                {citation.location.section && (
                                                                                    <Tag>{citation.location.section}</Tag>
                                                                                )}
                                                                                {citation.location.article_no && (
                                                                                    <Tag>{citation.location.article_no}</Tag>
                                                                                )}
                                                                            </div>
                                                                        </div>
                                                                        <Tooltip title="查看原文命中位置">
                                                                            <Button
                                                                                type="text"
                                                                                icon={<HighlightOutlined />}
                                                                                onClick={() => handleViewCitation(citation.citation_id)}
                                                                            />
                                                                        </Tooltip>
                                                                    </div>
                                                                ))}
                                                                <Collapse
                                                                    ghost
                                                                    className="chat-debug-panel"
                                                                    items={[
                                                                        {
                                                                            key: 'debug',
                                                                            label: (
                                                                                <span style={{ fontSize: 12, color: '#70675d' }}>
                                                                                    <BugOutlined style={{ marginRight: 6 }} />
                                                                                    检索评分细节
                                                                                </span>
                                                                            ),
                                                                            children: (
                                                                                <div>
                                                                                    {msg.citations.map((citation, index) => (
                                                                                        <div key={citation.citation_id} className="chat-debug-row">
                                                                                            <strong>[{index + 1}]</strong>{' '}
                                                                                            BM25={citation.scores.bm25.toFixed(3)}{' '}
                                                                                            Vector={citation.scores.vector.toFixed(3)}{' '}
                                                                                            RRF={citation.scores.rrf.toFixed(5)}{' '}
                                                                                            Rerank={citation.scores.rerank.toFixed(3)}
                                                                                        </div>
                                                                                    ))}
                                                                                </div>
                                                                            ),
                                                                        },
                                                                    ]}
                                                                />
                                                            </div>
                                                        )}
                                                    </>
                                                ) : (
                                                    <div className="chat-user-text">{msg.content}</div>
                                                )}
                                            </div>
                                        </div>
                                    </div>
                                ))}
                                <div ref={bottomRef} />
                            </div>
                        </main>

                        <footer className="chat-input-area">
                            <div className="chat-input-panel">
                                <div className="chat-input-label">
                                    <span className="chat-input-kicker">Ask With Evidence</span>
                                    <span className="chat-input-status">{statusSummary}</span>
                                </div>
                                <div className="chat-input-inner">
                                    <TextArea
                                        value={inputValue}
                                        onChange={(e) => setInputValue(e.target.value)}
                                        onPressEnter={(e) => {
                                            if (!e.shiftKey) {
                                                e.preventDefault()
                                                void handleSend()
                                            }
                                        }}
                                        placeholder="输入劳动法相关问题，按 Enter 发送，Shift + Enter 换行。"
                                        autoSize={{ minRows: 1, maxRows: 5 }}
                                        disabled={streaming}
                                        style={{ resize: 'none' }}
                                    />
                                    <Button
                                        className="chat-send-btn"
                                        type="primary"
                                        shape="circle"
                                        icon={<SendOutlined />}
                                        onClick={() => void handleSend()}
                                        disabled={!inputValue.trim() || streaming}
                                        loading={streaming}
                                    />
                                </div>
                            </div>
                            <div className="chat-input-disclaimer">
                                <InfoCircleOutlined />
                                你的问题和引用命中会保留在当前会话中，清空对话不会删除已上传文档索引。
                            </div>
                        </footer>
                    </section>
                </div>
            </div>

            <Drawer
                title="引用原文查看"
                placement="right"
                width={560}
                open={citationDrawerOpen}
                onClose={() => {
                    setCitationDrawerOpen(false)
                    setViewingCitation(null)
                }}
                styles={{ body: { background: '#fffaf2' } }}
            >
                {viewingCitationLoading ? (
                    <div style={{ textAlign: 'center', padding: 40 }}>
                        <Spin />
                    </div>
                ) : highlightPieces ? (
                    <div className="citation-viewer">
                        <div className="citation-meta">
                            <h3 className="citation-meta-title">引用定位</h3>
                            <p className="citation-meta-copy">文档 ID：{viewingCitation?.doc_id || '-'}</p>
                        </div>
                        {viewingCitation?.highlight.method === 'whole_chunk' && (
                            <div className="citation-fallback-notice">
                                <InfoCircleOutlined style={{ marginRight: 6 }} />
                                原文排版与切块边界存在偏差，当前以整段高亮方式展示命中内容。
                            </div>
                        )}
                        <div className="citation-context">
                            <span>{highlightPieces.before}</span>
                            <mark ref={highlightRef} className="citation-highlight">
                                {highlightPieces.hit}
                            </mark>
                            <span>{highlightPieces.after}</span>
                        </div>
                    </div>
                ) : (
                    <Empty description="暂无引用上下文" />
                )}
            </Drawer>
        </div>
    )
}
