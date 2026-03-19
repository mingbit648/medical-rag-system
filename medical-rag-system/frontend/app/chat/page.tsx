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
    buildFallbackSessionSummary,
    DRAFT_VIEW_KEY,
    remapOptimisticMessages,
    resolveInitialActiveView,
    sortChatMessages,
    sortConversations,
    upsertConversation,
    type ActiveView,
    type ChatMessage,
    type ConversationRecord,
    type DraftState,
} from '@/lib/chat/sessionState'
import {
    chatCompletionStream,
    chatSessionMessageStream,
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
const timeFormatter = new Intl.DateTimeFormat('zh-CN', { hour: '2-digit', minute: '2-digit' })
const dayFormatter = new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit' })

interface HighlightPieces {
    before: string
    hit: string
    after: string
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
        requestId: item.request_id,
        sessionSeq: typeof item.session_seq === 'number' ? item.session_seq : undefined,
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
    const latestMessage = [...sortChatMessages(conversation.messages)].reverse().find((item) => item.content.trim())
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
    const [activeView, setActiveView] = useState<ActiveView>({ kind: 'draft' })
    const [draftState, setDraftState] = useState<DraftState>({ input: '', messages: [] })
    const [sessionInput, setSessionInput] = useState('')
    const [bootstrapping, setBootstrapping] = useState(true)
    const [streamingViewKey, setStreamingViewKey] = useState('')
    const [citationDrawerOpen, setCitationDrawerOpen] = useState(false)
    const [viewingCitation, setViewingCitation] = useState<CitationViewData | null>(null)
    const [viewingCitationLoading, setViewingCitationLoading] = useState(false)
    const bottomRef = useRef<HTMLDivElement>(null)
    const highlightRef = useRef<HTMLElement>(null)

    const activeSessionId = activeView.kind === 'session' ? activeView.sessionId : ''
    const activeConversation = activeSessionId
        ? conversations.find((item) => item.session_id === activeSessionId) ?? null
        : null
    const currentMessages = activeView.kind === 'draft' ? draftState.messages : activeConversation?.messages ?? []
    const orderedMessages = sortChatMessages(currentMessages)
    const inputValue = activeView.kind === 'draft' ? draftState.input : sessionInput
    const highlightPieces = toHighlightPieces(viewingCitation)
    const citationCount = orderedMessages.reduce((sum, item) => sum + (item.citations?.length ?? 0), 0)
    const currentViewKey = activeView.kind === 'draft' ? DRAFT_VIEW_KEY : activeView.sessionId
    const streaming = Boolean(streamingViewKey) && streamingViewKey === currentViewKey
    const conversationStateLabel = bootstrapping
        ? '正在加载会话'
        : streaming
            ? '正在生成回复'
            : activeView.kind === 'draft'
                ? '新对话'
                : activeConversation?.status === 'archived'
                    ? '已归档会话'
                    : '准备就绪'

    useEffect(() => {
        let cancelled = false

        async function bootstrap() {
            try {
                const storedActive = window.localStorage.getItem(ACTIVE_STORAGE_KEY) || ''
                const listed = await listChatSessions()
                if (cancelled) return

                const mapped = sortConversations(listed.items.map((session) => ({ ...session, messages: [], loaded: false })))
                const nextActiveView = resolveInitialActiveView(mapped, storedActive)

                setConversations(mapped)
                setActiveView(nextActiveView)
                setSessionInput('')

                if (nextActiveView.kind === 'session') {
                    const detail = await getChatSessionDetail(nextActiveView.sessionId)
                    if (cancelled) return
                    setConversations((prev) =>
                        sortConversations(
                            prev.map((item) =>
                                item.session_id === nextActiveView.sessionId
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
        if (activeView.kind === 'session') {
            window.localStorage.setItem(ACTIVE_STORAGE_KEY, activeView.sessionId)
            return
        }
        window.localStorage.removeItem(ACTIVE_STORAGE_KEY)
    }, [activeView])

    useEffect(() => {
        if (!viewingCitation || viewingCitationLoading || !highlightRef.current) return
        window.setTimeout(() => highlightRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' }), 100)
    }, [viewingCitation, viewingCitationLoading])

    useEffect(() => {
        window.setTimeout(() => bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }), 60)
    }, [currentViewKey, currentMessages.length])

    useEffect(() => {
        if (activeView.kind !== 'session') return
        if (conversations.some((item) => item.session_id === activeView.sessionId)) return
        setActiveView(resolveInitialActiveView(conversations, ''))
        setSessionInput('')
    }, [activeView, conversations])

    function updateConversation(sessionId: string, updater: (conversation: ConversationRecord) => ConversationRecord) {
        setConversations((prev) => sortConversations(prev.map((item) => (item.session_id === sessionId ? updater(item) : item))))
    }

    function syncConversationSummary(
        session: ChatSessionSummary,
        options: { messages?: ChatMessage[]; loaded?: boolean } = {}
    ) {
        setConversations((prev) => {
            const existing = prev.find((item) => item.session_id === session.session_id)
            const merged: ConversationRecord = {
                ...mergeSummary(existing, session),
                messages: options.messages ?? existing?.messages ?? [],
                loaded: options.loaded ?? existing?.loaded ?? false,
            }
            return upsertConversation(prev, merged)
        })
    }

    function setComposerValue(value: string) {
        if (activeView.kind === 'draft') {
            setDraftState((prev) => ({ ...prev, input: value }))
            return
        }
        setSessionInput(value)
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
        if (streamingViewKey && streamingViewKey !== DRAFT_VIEW_KEY) {
            message.warning('当前有会话正在回复，请稍后再切换到新对话')
            return
        }
        if (activeView.kind === 'draft') return
        setActiveView({ kind: 'draft' })
        setSessionInput('')
    }

    async function handleSelectConversation(sessionId: string) {
        if (streamingViewKey && streamingViewKey !== sessionId) {
            message.warning('当前回复尚未完成，暂不允许切换会话')
            return
        }
        setActiveView({ kind: 'session', sessionId })
        setSessionInput('')
        try {
            await loadConversation(sessionId)
        } catch (err: any) {
            message.error(err?.message || '加载会话失败')
        }
    }

    async function handleDeleteConversation(sessionId: string) {
        if (streamingViewKey === sessionId) {
            message.warning('当前会话正在回复，暂不允许删除')
            return
        }
        try {
            await deleteChatSession(sessionId)
            const remaining = conversations.filter((item) => item.session_id !== sessionId)
            const sorted = sortConversations(remaining)
            setConversations(sorted)
            if (activeView.kind === 'session' && sessionId === activeView.sessionId) {
                if (sorted.length === 0) {
                    setActiveView({ kind: 'draft' })
                    setSessionInput('')
                    return
                }
                setActiveView({ kind: 'session', sessionId: sorted[0].session_id })
                setSessionInput('')
                await loadConversation(sorted[0].session_id)
            }
        } catch (err: any) {
            message.error(err?.message || '删除会话失败')
        }
    }

    async function handleSend() {
        const query = inputValue.trim()
        if (!query || streamingViewKey) return

        const now = Date.now()
        const requestId = `req_${now}_${Math.random().toString(36).slice(2, 8)}`
        const tempUserId = `temp_user_${requestId}`
        const tempAssistantId = `temp_assistant_${requestId}`
        const optimisticMessages: ChatMessage[] = [
            ...currentMessages,
            { id: tempUserId, role: 'user', content: query, timestamp: now, requestId, status: 'completed' },
            { id: tempAssistantId, role: 'assistant', content: '', timestamp: now + 1, requestId, status: 'streaming' },
        ]

        if (activeView.kind === 'draft') {
            let promotedSessionId = ''
            let userMessageId = tempUserId
            let assistantMessageId = tempAssistantId
            let assistantContent = ''

            const promoteDraftConversation = (payload: {
                session_id: string
                user_message_id?: string
                assistant_message_id?: string
                citations?: CitationItem[]
                session?: ChatSessionSummary
            }) => {
                userMessageId = payload.user_message_id || userMessageId
                assistantMessageId = payload.assistant_message_id || assistantMessageId
                const sessionSummary = payload.session || buildFallbackSessionSummary(payload.session_id, query, now)
                syncConversationSummary(sessionSummary, {
                    messages: remapOptimisticMessages(optimisticMessages, {
                        optimisticUserId: tempUserId,
                        optimisticAssistantId: tempAssistantId,
                        userMessageId,
                        assistantMessageId,
                        assistantContent,
                        citations: payload.citations,
                        assistantStatus: 'streaming',
                    }),
                    loaded: true,
                })
                promotedSessionId = sessionSummary.session_id
                setDraftState({ input: '', messages: [] })
                setActiveView({ kind: 'session', sessionId: sessionSummary.session_id })
                setSessionInput('')
                setStreamingViewKey(sessionSummary.session_id)
            }

            setDraftState({ input: '', messages: optimisticMessages })
            setStreamingViewKey(DRAFT_VIEW_KEY)

            try {
                await chatCompletionStream(
                    { query, request_id: requestId },
                    {
                        onMetadata: (payload) => {
                            if (!promotedSessionId) {
                                promoteDraftConversation(payload)
                                return
                            }
                            if (payload.session) {
                                syncConversationSummary(payload.session)
                            }
                        },
                        onToken: (token) => {
                            assistantContent += token
                            if (promotedSessionId) {
                                updateConversation(promotedSessionId, (item) => ({
                                    ...item,
                                    updated_at: new Date().toISOString(),
                                    messages: item.messages.map((messageItem) =>
                                        messageItem.id === assistantMessageId
                                            ? { ...messageItem, content: messageItem.content + token }
                                            : messageItem
                                    ),
                                }))
                                return
                            }
                            setDraftState((prev) => ({
                                ...prev,
                                messages: prev.messages.map((messageItem) =>
                                    messageItem.id === tempAssistantId
                                        ? { ...messageItem, content: messageItem.content + token }
                                        : messageItem
                                ),
                            }))
                        },
                        onDone: (payload) => {
                            if (!promotedSessionId) {
                                promoteDraftConversation(payload)
                            }
                            userMessageId = payload.user_message_id || userMessageId
                            assistantMessageId = payload.assistant_message_id || assistantMessageId
                            updateConversation(payload.session_id, (item) => ({
                                ...mergeSummary(item, payload.session || item),
                                messages: remapOptimisticMessages(item.messages, {
                                    optimisticUserId: tempUserId,
                                    optimisticAssistantId: tempAssistantId,
                                    userMessageId,
                                    assistantMessageId,
                                    assistantContent,
                                    citations: payload.citations,
                                    assistantStatus: 'completed',
                                }),
                                loaded: true,
                            }))
                        },
                        onError: (errMsg) => {
                            const failureText = assistantContent || `生成失败：${errMsg}`
                            if (promotedSessionId) {
                                updateConversation(promotedSessionId, (item) => ({
                                    ...item,
                                    updated_at: new Date().toISOString(),
                                    messages: item.messages.map((messageItem) =>
                                        messageItem.id === assistantMessageId
                                            ? { ...messageItem, status: 'error', content: failureText }
                                            : messageItem
                                    ),
                                }))
                                return
                            }
                            setDraftState((prev) => ({
                                ...prev,
                                messages: prev.messages.map((messageItem) =>
                                    messageItem.id === tempAssistantId
                                        ? { ...messageItem, status: 'error', content: failureText }
                                        : messageItem
                                ),
                            }))
                        },
                    }
                )
                if (promotedSessionId) {
                    await loadConversation(promotedSessionId, true)
                }
            } catch (err: any) {
                const failureText = assistantContent || `请求失败：${err?.message || '未知错误'}`
                if (promotedSessionId) {
                    updateConversation(promotedSessionId, (item) => ({
                        ...item,
                        updated_at: new Date().toISOString(),
                        messages: item.messages.map((messageItem) =>
                            messageItem.id === assistantMessageId
                                ? { ...messageItem, status: 'error', content: failureText }
                                : messageItem
                        ),
                    }))
                } else {
                    setDraftState((prev) => ({
                        ...prev,
                        messages: prev.messages.map((messageItem) =>
                            messageItem.id === tempAssistantId
                                ? { ...messageItem, status: 'error', content: failureText }
                                : messageItem
                        ),
                    }))
                }
            } finally {
                setStreamingViewKey('')
            }
            return
        }

        if (!activeConversation) return

        const sessionId = activeConversation.session_id
        let userMessageId = tempUserId
        let assistantMessageId = tempAssistantId

        updateConversation(sessionId, (item) => ({
            ...item,
            messages: optimisticMessages,
            loaded: true,
            preview: query,
            updated_at: new Date(now).toISOString(),
            message_count: item.message_count + 2,
            title: item.title || query.slice(0, 28),
        }))
        setSessionInput('')
        setStreamingViewKey(sessionId)

        try {
            await chatSessionMessageStream(
                sessionId,
                { query, request_id: requestId },
                {
                    onMetadata: (payload) => {
                        userMessageId = payload.user_message_id || userMessageId
                        assistantMessageId = payload.assistant_message_id || assistantMessageId
                        updateConversation(sessionId, (item) => ({
                            ...mergeSummary(item, payload.session || item),
                            messages: remapOptimisticMessages(item.messages, {
                                optimisticUserId: tempUserId,
                                optimisticAssistantId: tempAssistantId,
                                userMessageId,
                                assistantMessageId,
                                assistantStatus: 'streaming',
                            }),
                            loaded: true,
                        }))
                    },
                    onToken: (token) => {
                        updateConversation(sessionId, (item) => ({
                            ...item,
                            updated_at: new Date().toISOString(),
                            messages: item.messages.map((messageItem) =>
                                messageItem.id === assistantMessageId
                                    ? { ...messageItem, content: messageItem.content + token }
                                    : messageItem
                            ),
                        }))
                    },
                    onDone: (payload) => {
                        userMessageId = payload.user_message_id || userMessageId
                        assistantMessageId = payload.assistant_message_id || assistantMessageId
                        updateConversation(sessionId, (item) => ({
                            ...mergeSummary(item, payload.session || item),
                            messages: remapOptimisticMessages(item.messages, {
                                optimisticUserId: tempUserId,
                                optimisticAssistantId: tempAssistantId,
                                userMessageId,
                                assistantMessageId,
                                citations: payload.citations,
                                assistantStatus: 'completed',
                            }),
                            loaded: true,
                        }))
                    },
                    onError: (errMsg) => {
                        updateConversation(sessionId, (item) => ({
                            ...item,
                            updated_at: new Date().toISOString(),
                            messages: item.messages.map((messageItem) =>
                                messageItem.id === assistantMessageId || messageItem.id === tempAssistantId
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
            await loadConversation(sessionId, true)
        } catch (err: any) {
            updateConversation(sessionId, (item) => ({
                ...item,
                updated_at: new Date().toISOString(),
                messages: item.messages.map((messageItem) =>
                    messageItem.id === assistantMessageId || messageItem.id === tempAssistantId
                        ? { ...messageItem, status: 'error', content: `请求失败：${err?.message || '未知错误'}` }
                        : messageItem
                ),
            }))
        } finally {
            setStreamingViewKey('')
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
                                    className={`chat-session-item${activeView.kind === 'session' && conversation.session_id === activeView.sessionId ? ' active' : ''}`}
                                    onClick={() => void handleSelectConversation(conversation.session_id)}
                                >
                                    <div className="chat-session-copy">
                                        <span className="chat-session-title">{conversation.title}</span>
                                        <span className="chat-session-preview">{getConversationPreview(conversation)}</span>
                                    </div>
                                    <div className="chat-session-meta">
                                        <span className="chat-session-count">
                                            {conversation.message_count > 0 ? `${conversation.message_count} 条消息` : '空会话'}
                                        </span>
                                        <span className="chat-session-time">{formatConversationTime(conversation.updated_at)}</span>
                                    </div>
                                </button>
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
                            </div>
                        ))}
                    </div>
                </aside>

                <section className="chat-main">
                    <header className="chat-main-header">
                        <div className="chat-main-heading">
                            <span className="chat-main-kicker">{conversationStateLabel}</span>
                            <h1 className="chat-main-title">{bootstrapping ? '加载中' : activeConversation?.title || '开始新对话'}</h1>
                            <p className="chat-main-meta">
                                {bootstrapping
                                    ? '正在加载会话'
                                    : currentMessages.length > 0
                                        ? `${currentMessages.length} 条消息 · ${citationCount} 条引用`
                                        : '开始新会话'}
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
                                    <p className="chat-empty-copy">描述时间、地区、劳动关系和你的目标。</p>
                                    <div className="chat-empty-prompts">
                                        {QUICK_PROMPTS.map((prompt) => (
                                            <button
                                                key={prompt}
                                                type="button"
                                                className="chat-empty-prompt"
                                                onClick={() => setComposerValue(prompt)}
                                            >
                                                {prompt}
                                            </button>
                                        ))}
                                    </div>
                                </section>
                            ) : (
                                orderedMessages.map((msg) => (
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
                            <div className="chat-composer">
                                <div className="chat-input-inner">
                                    <div className="chat-input-editor">
                                        <TextArea
                                            value={inputValue}
                                            onChange={(e) => setComposerValue(e.target.value)}
                                            onPressEnter={(e) => {
                                                if (!e.shiftKey) {
                                                    e.preventDefault()
                                                    void handleSend()
                                                }
                                            }}
                                            placeholder="输入问题"
                                            autoSize={{ minRows: 1, maxRows: 8 }}
                                            disabled={bootstrapping || streaming || (activeView.kind === 'session' && !activeConversation)}
                                            style={{ resize: 'none' }}
                                        />
                                    </div>
                                    <button
                                        type="button"
                                        className="chat-send-btn"
                                        onClick={() => void handleSend()}
                                        disabled={!inputValue.trim() || bootstrapping || streaming || (activeView.kind === 'session' && !activeConversation)}
                                        aria-label="发送消息"
                                    >
                                        <SendOutlined />
                                    </button>
                                </div>
                                <div className="chat-input-hint">{streaming ? '正在生成回复' : 'Enter 发送 · Shift + Enter 换行'}</div>
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
