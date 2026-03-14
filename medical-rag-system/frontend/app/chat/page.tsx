'use client'

import { useEffect, useRef, useState } from 'react'
import Link from 'next/link'
import { Drawer, Empty, Input, Spin, Tooltip, message } from 'antd'
import {
    DatabaseOutlined,
    DeleteOutlined,
    ExportOutlined,
    HighlightOutlined,
    InfoCircleOutlined,
    PlusOutlined,
    SendOutlined,
} from '@ant-design/icons'
import MarkdownIt from 'markdown-it'
import { resolveApiUrl } from '@/lib/api/client'
import {
    chatSessionMessageStream,
    createChatSession,
    deleteChatSession,
    getChatSessionDetail,
    getCitationOpenTarget,
    getCitationView,
    listChatSessions,
    type ChatHistoryMessage,
    type ChatSessionSummary,
    type CitationItem,
    type CitationViewData,
} from '@/lib/api/legalRag'

const { TextArea } = Input
const md = new MarkdownIt({ html: false, linkify: true, typographer: true })
const QUICK_PROMPTS = [
    '公司拖欠工资，劳动仲裁前要准备哪些证据？',
    '劳动合同到期不续签，经济补偿怎么算？',
    '被违法辞退后，申请仲裁的常见步骤是什么？',
]
const ACTIVE_STORAGE_KEY = 'legal-rag-chat-active-session'
const DRAFTS_STORAGE_KEY = 'legal-rag-chat-drafts'
const timeFormatter = new Intl.DateTimeFormat('zh-CN', { hour: '2-digit', minute: '2-digit' })
const dayFormatter = new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit' })

interface ChatMessage {
    id: string
    role: 'user' | 'assistant'
    content: string
    citations?: CitationItem[]
    timestamp: number
    status: 'streaming' | 'completed' | 'error'
}

interface ConversationRecord extends ChatSessionSummary {
    messages: ChatMessage[]
    loaded: boolean
}

interface HighlightPieces {
    before: string
    hit: string
    after: string
}

function sortConversations(items: ConversationRecord[]) {
    return [...items].sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime())
}

function formatConversationTime(timestamp: string) {
    const date = new Date(timestamp)
    const now = new Date()
    const isSameDay =
        date.getFullYear() === now.getFullYear() &&
        date.getMonth() === now.getMonth() &&
        date.getDate() === now.getDate()
    return isSameDay ? timeFormatter.format(date) : dayFormatter.format(date)
}

function mapServerMessage(item: ChatHistoryMessage): ChatMessage | null {
    if ((item.role !== 'user' && item.role !== 'assistant') || typeof item.content !== 'string') return null
    return {
        id: item.message_id || item.msg_id,
        role: item.role,
        content: item.content,
        citations: item.citations,
        timestamp: new Date(item.created_at).getTime(),
        status: (item.status as ChatMessage['status']) || 'completed',
    }
}

function mergeSummary(existing: ConversationRecord | undefined, session: ChatSessionSummary): ConversationRecord {
    return {
        ...existing,
        ...session,
        messages: existing?.messages || [],
        loaded: existing?.loaded || false,
    }
}

function getConversationPreview(conversation: ConversationRecord) {
    const latestMessage = [...conversation.messages].reverse().find((item) => item.content.trim())
    if (latestMessage) return latestMessage.content.replace(/\s+/g, ' ').trim().slice(0, 42)
    return (conversation.preview || '空白对话').replace(/\s+/g, ' ').trim().slice(0, 42)
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

function resolveOpenTargetUrl(url: string) {
    if (!url || /^https?:\/\//.test(url) || !url.startsWith('/api/')) return url
    const hashIndex = url.indexOf('#')
    const path = hashIndex >= 0 ? url.slice(0, hashIndex) : url
    const hash = hashIndex >= 0 ? url.slice(hashIndex) : ''
    return `${resolveApiUrl(path)}${hash}`
}

export default function ChatPage() {
    const [conversations, setConversations] = useState<ConversationRecord[]>([])
    const [activeConversationId, setActiveConversationId] = useState('')
    const [drafts, setDrafts] = useState<Record<string, string>>({})
    const [bootstrapping, setBootstrapping] = useState(true)
    const [streamingSessionId, setStreamingSessionId] = useState('')
    const [citationDrawerOpen, setCitationDrawerOpen] = useState(false)
    const [viewingCitation, setViewingCitation] = useState<CitationViewData | null>(null)
    const [viewingCitationLoading, setViewingCitationLoading] = useState(false)
    const bottomRef = useRef<HTMLDivElement>(null)
    const highlightRef = useRef<HTMLElement>(null)

    const activeConversation = conversations.find((item) => item.session_id === activeConversationId) ?? null
    const currentMessages = activeConversation?.messages ?? []
    const inputValue = drafts[activeConversationId] || ''
    const highlightPieces = toHighlightPieces(viewingCitation)
    const citationCount = currentMessages.reduce((sum, item) => sum + (item.citations?.length ?? 0), 0)
    const streaming = streamingSessionId === activeConversationId
    const conversationStateLabel = streaming
        ? '正在生成回复'
        : activeConversation?.status === 'archived'
            ? '已归档会话'
            : activeConversation
                ? '知识库会话已连接'
                : '正在加载会话'

    useEffect(() => {
        let cancelled = false

        async function bootstrap() {
            try {
                const storedActive = window.localStorage.getItem(ACTIVE_STORAGE_KEY) || ''
                const storedDrafts = window.localStorage.getItem(DRAFTS_STORAGE_KEY)
                if (storedDrafts) {
                    try {
                        setDrafts(JSON.parse(storedDrafts))
                    } catch {
                        setDrafts({})
                    }
                }

                const listed = await listChatSessions()
                const items = listed.items.length > 0 ? listed.items : [await createChatSession()]
                if (cancelled) return

                const mapped = sortConversations(items.map((session) => ({ ...session, messages: [], loaded: false })))
                const nextActiveId = mapped.some((item) => item.session_id === storedActive)
                    ? storedActive
                    : mapped[0]?.session_id || ''

                setConversations(mapped)
                setActiveConversationId(nextActiveId)

                if (nextActiveId) {
                    const detail = await getChatSessionDetail(nextActiveId)
                    if (cancelled) return
                    setConversations((prev) =>
                        sortConversations(
                            prev.map((item) =>
                                item.session_id === nextActiveId
                                    ? {
                                        ...mergeSummary(item, detail.session),
                                        messages: detail.messages.map(mapServerMessage).filter(Boolean) as ChatMessage[],
                                        loaded: true,
                                    }
                                    : item
                            )
                        )
                    )
                }
            } catch (err: any) {
                message.error(err?.message || '加载会话失败')
            } finally {
                if (!cancelled) setBootstrapping(false)
            }
        }

        void bootstrap()
        return () => {
            cancelled = true
        }
    }, [])

    useEffect(() => {
        if (!activeConversationId) return
        window.localStorage.setItem(ACTIVE_STORAGE_KEY, activeConversationId)
    }, [activeConversationId])

    useEffect(() => {
        window.localStorage.setItem(DRAFTS_STORAGE_KEY, JSON.stringify(drafts))
    }, [drafts])

    useEffect(() => {
        if (!viewingCitation || viewingCitationLoading || !highlightRef.current) return
        window.setTimeout(() => highlightRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' }), 100)
    }, [viewingCitation, viewingCitationLoading])

    useEffect(() => {
        window.setTimeout(() => bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }), 60)
    }, [activeConversationId, currentMessages.length])

    function updateConversation(sessionId: string, updater: (conversation: ConversationRecord) => ConversationRecord) {
        setConversations((prev) => sortConversations(prev.map((item) => (item.session_id === sessionId ? updater(item) : item))))
    }

    async function loadConversation(sessionId: string, force = false) {
        const target = conversations.find((item) => item.session_id === sessionId)
        if (!force && target?.loaded) return
        const detail = await getChatSessionDetail(sessionId)
        setConversations((prev) =>
            sortConversations(
                prev.map((item) =>
                    item.session_id === sessionId
                        ? {
                            ...mergeSummary(item, detail.session),
                            messages: detail.messages.map(mapServerMessage).filter(Boolean) as ChatMessage[],
                            loaded: true,
                        }
                        : item
                )
            )
        )
    }

    async function handleNewConversation() {
        if (streamingSessionId) {
            message.warning('当前有会话正在回复，请稍后再创建新会话')
            return
        }
        try {
            const created = await createChatSession()
            setConversations((prev) => sortConversations([{ ...created, messages: [], loaded: true }, ...prev]))
            setActiveConversationId(created.session_id)
        } catch (err: any) {
            message.error(err?.message || '创建会话失败')
        }
    }

    async function handleSelectConversation(sessionId: string) {
        if (streamingSessionId && sessionId !== activeConversationId) {
            message.warning('当前回复尚未完成，暂不允许切换会话')
            return
        }
        setActiveConversationId(sessionId)
        try {
            await loadConversation(sessionId)
        } catch (err: any) {
            message.error(err?.message || '加载会话失败')
        }
    }

    async function handleDeleteConversation(sessionId: string) {
        if (streamingSessionId === sessionId) {
            message.warning('当前会话正在回复，暂不允许删除')
            return
        }
        try {
            await deleteChatSession(sessionId)
            const remaining = conversations.filter((item) => item.session_id !== sessionId)
            if (remaining.length === 0) {
                const created = await createChatSession()
                setConversations([{ ...created, messages: [], loaded: true }])
                setActiveConversationId(created.session_id)
                return
            }
            const sorted = sortConversations(remaining)
            setConversations(sorted)
            if (sessionId === activeConversationId) {
                setActiveConversationId(sorted[0].session_id)
                await loadConversation(sorted[0].session_id)
            }
        } catch (err: any) {
            message.error(err?.message || '删除会话失败')
        }
    }

    async function handleSend() {
        if (!activeConversation) return
        const query = inputValue.trim()
        if (!query || streamingSessionId) return

        const now = Date.now()
        const requestId = `req_${now}_${Math.random().toString(36).slice(2, 8)}`
        const tempUserId = `temp_user_${requestId}`
        const tempAssistantId = `temp_assistant_${requestId}`
        const optimisticMessages: ChatMessage[] = [
            ...currentMessages,
            { id: tempUserId, role: 'user', content: query, timestamp: now, status: 'completed' },
            { id: tempAssistantId, role: 'assistant', content: '', timestamp: now + 1, status: 'streaming' },
        ]

        updateConversation(activeConversation.session_id, (item) => ({
            ...item,
            messages: optimisticMessages,
            loaded: true,
            preview: query,
            updated_at: new Date(now).toISOString(),
            message_count: item.message_count + 2,
            title: item.title || query.slice(0, 28),
        }))
        setDrafts((prev) => ({ ...prev, [activeConversation.session_id]: '' }))
        setStreamingSessionId(activeConversation.session_id)

        try {
            await chatSessionMessageStream(
                activeConversation.session_id,
                { query, request_id: requestId },
                {
                    onMetadata: (payload) => {
                        if (payload.session) {
                            updateConversation(activeConversation.session_id, (item) => mergeSummary(item, payload.session!))
                        }
                    },
                    onToken: (token) => {
                        updateConversation(activeConversation.session_id, (item) => ({
                            ...item,
                            updated_at: new Date().toISOString(),
                            messages: item.messages.map((messageItem) =>
                                messageItem.id === tempAssistantId
                                    ? { ...messageItem, content: messageItem.content + token }
                                    : messageItem
                            ),
                        }))
                    },
                    onDone: (payload) => {
                        updateConversation(activeConversation.session_id, (item) => ({
                            ...mergeSummary(item, payload.session || item),
                            messages: item.messages.map((messageItem) =>
                                messageItem.id === tempAssistantId
                                    ? { ...messageItem, citations: payload.citations, status: 'completed' }
                                    : messageItem
                            ),
                            loaded: true,
                        }))
                    },
                    onError: (errMsg) => {
                        updateConversation(activeConversation.session_id, (item) => ({
                            ...item,
                            updated_at: new Date().toISOString(),
                            messages: item.messages.map((messageItem) =>
                                messageItem.id === tempAssistantId
                                    ? {
                                        ...messageItem,
                                        status: 'error',
                                        content: messageItem.content || `生成失败：${errMsg}`,
                                    }
                                    : messageItem
                            ),
                        }))
                    },
                }
            )
            await loadConversation(activeConversation.session_id, true)
        } catch (err: any) {
            updateConversation(activeConversation.session_id, (item) => ({
                ...item,
                updated_at: new Date().toISOString(),
                messages: item.messages.map((messageItem) =>
                    messageItem.id === tempAssistantId
                        ? { ...messageItem, status: 'error', content: `请求失败：${err?.message || '未知错误'}` }
                        : messageItem
                ),
            }))
        } finally {
            setStreamingSessionId('')
        }
    }

    async function handleViewCitation(citationId: string) {
        setCitationDrawerOpen(true)
        setViewingCitation(null)
        setViewingCitationLoading(true)
        try {
            setViewingCitation(await getCitationView(citationId))
        } catch (err: any) {
            message.error(`查看引用失败：${err?.message || '未知错误'}`)
        } finally {
            setViewingCitationLoading(false)
        }
    }

    async function handleOpenCitationOriginal(citation: CitationItem) {
        try {
            const target = await getCitationOpenTarget(citation.citation_id)
            window.open(resolveOpenTargetUrl(target.url), '_blank', 'noopener,noreferrer')
        } catch (err: any) {
            message.error(`打开原文失败：${err?.message || '未知错误'}`)
        }
    }

    return (
        <div className="chat-page">
            <div className="chat-shell">
                <aside className="chat-sidebar">
                    <div className="chat-sidebar-intro">
                        <span className="chat-sidebar-kicker">LEGAL DESK</span>
                        <div className="chat-sidebar-heading">
                            <h2 className="chat-sidebar-title">法律咨询工作台</h2>
                            <p className="chat-sidebar-copy">会话、历史消息和上下文摘要已切换为服务端管理。</p>
                        </div>
                        <div className="chat-sidebar-stats">
                            <span>{conversations.length} 个会话</span>
                            <span>{currentMessages.length} 条消息</span>
                        </div>
                    </div>

                    <div className="chat-sidebar-top">
                        <button type="button" className="chat-new-thread" onClick={() => void handleNewConversation()}>
                            <PlusOutlined />
                            新建对话
                        </button>
                    </div>

                    <div className="chat-session-list">
                        {conversations.map((conversation) => (
                            <div key={conversation.session_id} className="chat-session-row">
                                <button
                                    type="button"
                                    className={`chat-session-item${conversation.session_id === activeConversationId ? ' active' : ''}`}
                                    onClick={() => void handleSelectConversation(conversation.session_id)}
                                >
                                    <span className="chat-session-title">{conversation.title}</span>
                                    <span className="chat-session-preview">{getConversationPreview(conversation)}</span>
                                    <span className="chat-session-time">{formatConversationTime(conversation.updated_at)}</span>
                                </button>
                                {conversations.length > 1 ? (
                                    <Tooltip title="删除对话">
                                        <button
                                            type="button"
                                            className="chat-session-delete"
                                            onClick={() => void handleDeleteConversation(conversation.session_id)}
                                            aria-label="删除对话"
                                        >
                                            <DeleteOutlined />
                                        </button>
                                    </Tooltip>
                                ) : null}
                            </div>
                        ))}
                    </div>
                </aside>

                <section className="chat-main">
                    <header className="chat-main-header">
                        <div className="chat-main-heading">
                            <span className="chat-main-kicker">{conversationStateLabel}</span>
                            <h1 className="chat-main-title">{activeConversation?.title || '加载中'}</h1>
                            <p className="chat-main-meta">
                                {bootstrapping
                                    ? '正在同步服务端会话'
                                    : currentMessages.length > 0
                                        ? `${currentMessages.length} 条消息 · ${citationCount} 条引用`
                                        : '从服务端新建会话开始，消息和上下文均持久化到数据库'}
                            </p>
                        </div>
                        <div className="chat-main-actions">
                            <span className="chat-main-hint">{streaming ? '正在生成回答...' : 'Enter 发送 · Shift + Enter 换行'}</span>
                            <Link href="/knowledge" className="chat-knowledge-link">
                                <DatabaseOutlined />
                                知识库
                            </Link>
                        </div>
                    </header>

                    <main className="chat-messages">
                        <div className="chat-thread">
                            {bootstrapping ? (
                                <div style={{ padding: 48, textAlign: 'center' }}>
                                    <Spin />
                                </div>
                            ) : currentMessages.length === 0 ? (
                                <section className="chat-empty">
                                    <span className="chat-empty-kicker">START WITH FACTS</span>
                                    <h2 className="chat-empty-title">开始新对话</h2>
                                    <p className="chat-empty-copy">描述时间、地区、劳动关系和你的目标，服务端会话会自动记录历史与上下文。</p>
                                    <div className="chat-empty-prompts">
                                        {QUICK_PROMPTS.map((prompt) => (
                                            <button
                                                key={prompt}
                                                type="button"
                                                className="chat-empty-prompt"
                                                onClick={() => setDrafts((prev) => ({ ...prev, [activeConversationId]: prompt }))}
                                            >
                                                {prompt}
                                            </button>
                                        ))}
                                    </div>
                                </section>
                            ) : (
                                currentMessages.map((msg) => (
                                    <div key={msg.id} className={`chat-message-row ${msg.role}`}>
                                        <div className={`chat-bubble ${msg.role}`}>
                                            {msg.role === 'assistant' ? (
                                                <>
                                                    {msg.content ? (
                                                        <div className="chat-markdown" dangerouslySetInnerHTML={{ __html: md.render(msg.content) }} />
                                                    ) : (
                                                        <Spin size="small" />
                                                    )}
                                                    {msg.citations?.length ? (
                                                        <div className="chat-citations">
                                                            {msg.citations.map((citation) => (
                                                                <div key={citation.citation_id} className="chat-citation-item">
                                                                    <div className="chat-citation-body">
                                                                        <div className="chat-citation-title">{citation.source.title}</div>
                                                                        <div className="chat-citation-snippet">{citation.snippet}</div>
                                                                    </div>
                                                                    <div className="chat-citation-actions">
                                                                        <Tooltip title="在新标签页打开原文定位">
                                                                            <button
                                                                                type="button"
                                                                                className="chat-citation-action primary"
                                                                                onClick={() => void handleOpenCitationOriginal(citation)}
                                                                            >
                                                                                <ExportOutlined />
                                                                                <span>打开原文</span>
                                                                            </button>
                                                                        </Tooltip>
                                                                        <Tooltip title="查看当前摘录定位">
                                                                            <button
                                                                                type="button"
                                                                                className="chat-citation-action secondary"
                                                                                onClick={() => void handleViewCitation(citation.citation_id)}
                                                                            >
                                                                                <HighlightOutlined />
                                                                                <span>查看摘录</span>
                                                                            </button>
                                                                        </Tooltip>
                                                                    </div>
                                                                </div>
                                                            ))}
                                                        </div>
                                                    ) : null}
                                                </>
                                            ) : (
                                                <div className="chat-user-text">{msg.content}</div>
                                            )}
                                        </div>
                                    </div>
                                ))
                            )}
                            <div ref={bottomRef} />
                        </div>
                    </main>

                    <footer className="chat-input-area">
                        <div className="chat-input-panel">
                            <div className="chat-input-inner">
                                <TextArea
                                    value={inputValue}
                                    onChange={(e) => setDrafts((prev) => ({ ...prev, [activeConversationId]: e.target.value }))}
                                    onPressEnter={(e) => {
                                        if (!e.shiftKey) {
                                            e.preventDefault()
                                            void handleSend()
                                        }
                                    }}
                                    placeholder="输入问题，消息与上下文会持久化到数据库"
                                    autoSize={{ minRows: 1, maxRows: 8 }}
                                    disabled={!activeConversationId || streaming}
                                    style={{ resize: 'none' }}
                                />
                                <button
                                    type="button"
                                    className="chat-send-btn"
                                    onClick={() => void handleSend()}
                                    disabled={!inputValue.trim() || !activeConversationId || streaming}
                                    aria-label="发送消息"
                                >
                                    <SendOutlined />
                                </button>
                            </div>
                        </div>
                    </footer>
                </section>
            </div>

            <Drawer
                title="引用原文"
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
                        {viewingCitation?.highlight.method === 'whole_chunk' ? (
                            <div className="citation-fallback-notice">
                                <InfoCircleOutlined style={{ marginRight: 6 }} />
                                当前以整段高亮方式展示命中内容。
                            </div>
                        ) : null}
                        <div className="citation-context">
                            <span>{highlightPieces.before}</span>
                            <mark ref={highlightRef} className="citation-highlight">{highlightPieces.hit}</mark>
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
