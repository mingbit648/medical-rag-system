'use client'

import {
    Button,
    Drawer,
    Empty,
    Input,
    Layout,
    List,
    Select,
    Space,
    Spin,
    Typography,
    message,
} from 'antd'
import MarkdownIt from 'markdown-it'
import { useCallback, useEffect, useState } from 'react'
import { LogoutOutlined } from '@ant-design/icons'
import { useRouter } from 'next/navigation'
import AuthGuard from '@/components/AuthGuard'
import { resolveApiUrl } from '@/lib/api/client'
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
import { buildScopedStorageKey, useAppSession } from '@/lib/session/AppSessionProvider'


const { Header, Sider, Content } = Layout
const { TextArea } = Input
const md = new MarkdownIt({ html: false, linkify: true, typographer: true })


interface UiMessage {
    id: string
    role: 'user' | 'assistant'
    content: string
    citations?: CitationItem[]
    requestId?: string
    status: 'streaming' | 'completed' | 'error'
    timestamp: number
}


interface ConversationRecord extends ChatSessionSummary {
    messages: UiMessage[]
    loaded: boolean
}


function mapServerMessage(item: ChatHistoryMessage): UiMessage | null {
    if (item.role !== 'user' && item.role !== 'assistant') return null
    return {
        id: item.message_id || item.msg_id,
        role: item.role,
        content: item.content,
        citations: item.citations,
        requestId: item.request_id,
        status: (item.status as UiMessage['status']) || 'completed',
        timestamp: new Date(item.created_at).getTime(),
    }
}


function sortSessions(items: ConversationRecord[]): ConversationRecord[] {
    return [...items].sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime())
}


function sortMessages(items: UiMessage[]): UiMessage[] {
    return [...items].sort((a, b) => a.timestamp - b.timestamp)
}


function upsertSession(items: ConversationRecord[], nextItem: ConversationRecord): ConversationRecord[] {
    const exists = items.some((item) => item.session_id === nextItem.session_id)
    return sortSessions(
        exists
            ? items.map((item) => (item.session_id === nextItem.session_id ? nextItem : item))
            : [nextItem, ...items]
    )
}


function buildFallbackSession(sessionId: string, kbId: string, kbName: string | null, query: string): ChatSessionSummary {
    const now = new Date().toISOString()
    return {
        session_id: sessionId,
        kb_id: kbId,
        kb_name: kbName,
        title: query.slice(0, 28) || '新对话',
        status: 'active',
        preview: query.slice(0, 80),
        message_count: 2,
        created_at: now,
        updated_at: now,
        last_active_at: now,
        active_summary_id: null,
    }
}


function resolveTargetUrl(url: string): string {
    if (!url || /^https?:\/\//.test(url) || !url.startsWith('/api/')) return url
    const hashIndex = url.indexOf('#')
    const path = hashIndex >= 0 ? url.slice(0, hashIndex) : url
    const hash = hashIndex >= 0 ? url.slice(hashIndex) : ''
    return `${resolveApiUrl(path)}${hash}`
}


function getActiveSessionStorageKey(userId: string, kbId: string): string {
    return buildScopedStorageKey(userId, `chat:${kbId}:active-session`)
}


function getDraftStorageKey(userId: string, kbId: string): string {
    return buildScopedStorageKey(userId, `chat:${kbId}:draft`)
}


function ChatWorkspace() {
    const router = useRouter()
    const { user, knowledgeBases, currentKnowledgeBase, currentKnowledgeBaseId, selectKnowledgeBase, logout } = useAppSession()
    const [sessions, setSessions] = useState<ConversationRecord[]>([])
    const [activeSessionId, setActiveSessionId] = useState<string | null>(null)
    const [draftMessages, setDraftMessages] = useState<UiMessage[]>([])
    const [inputValue, setInputValue] = useState('')
    const [loadingSessions, setLoadingSessions] = useState(false)
    const [streaming, setStreaming] = useState(false)
    const [citationDrawerOpen, setCitationDrawerOpen] = useState(false)
    const [citationView, setCitationView] = useState<CitationViewData | null>(null)
    const [citationLoading, setCitationLoading] = useState(false)

    const activeConversation = sessions.find((item) => item.session_id === activeSessionId) || null
    const currentMessages = activeConversation ? activeConversation.messages : draftMessages

    const persistDraft = useCallback(
        (value: string) => {
            if (typeof window === 'undefined' || !user?.user_id || !currentKnowledgeBaseId) return
            window.localStorage.setItem(getDraftStorageKey(user.user_id, currentKnowledgeBaseId), value)
        },
        [currentKnowledgeBaseId, user?.user_id]
    )

    const loadSessionDetail = useCallback(async (sessionId: string) => {
        const detail = await getChatSessionDetail(sessionId)
        setSessions((prev) =>
            sortSessions(
                prev.map((item) =>
                    item.session_id === sessionId
                        ? {
                            ...item,
                            ...detail.session,
                            messages: detail.messages.map(mapServerMessage).filter(Boolean) as UiMessage[],
                            loaded: true,
                        }
                        : item
                )
            )
        )
    }, [])

    useEffect(() => {
        const userId = user?.user_id
        const kbId = currentKnowledgeBaseId
        if (!userId || !kbId) return
        const resolvedUserId: string = userId
        const resolvedKbId: string = kbId
        let cancelled = false

        async function bootstrapSessions() {
            setLoadingSessions(true)
            setSessions([])
            setActiveSessionId(null)
            setDraftMessages([])
            try {
                const storedDraft = window.localStorage.getItem(getDraftStorageKey(resolvedUserId, resolvedKbId)) || ''
                setInputValue(storedDraft)
                const listed = await listChatSessions(resolvedKbId)
                if (cancelled) return
                const nextSessions = sortSessions(
                    (listed.items || []).map((session) => ({ ...session, messages: [], loaded: false }))
                )
                setSessions(nextSessions)
                const storedActive = window.localStorage.getItem(getActiveSessionStorageKey(resolvedUserId, resolvedKbId))
                const nextActive =
                    nextSessions.find((item) => item.session_id === storedActive)?.session_id ||
                    nextSessions[0]?.session_id ||
                    null
                setActiveSessionId(nextActive)
                if (nextActive) {
                    await loadSessionDetail(nextActive)
                }
            } catch (err: any) {
                message.error(err?.message || '加载会话失败')
            } finally {
                if (!cancelled) {
                    setLoadingSessions(false)
                }
            }
        }

        void bootstrapSessions()
        return () => {
            cancelled = true
        }
    }, [currentKnowledgeBaseId, loadSessionDetail, user?.user_id])

    useEffect(() => {
        const userId = user?.user_id
        const kbId = currentKnowledgeBaseId
        if (!userId || !kbId) return
        const activeKey = getActiveSessionStorageKey(userId as string, kbId as string)
        if (activeSessionId) {
            window.localStorage.setItem(activeKey, activeSessionId)
        } else {
            window.localStorage.removeItem(activeKey)
        }
    }, [activeSessionId, currentKnowledgeBaseId, user?.user_id])

    async function handleSwitchKnowledgeBase(kbId: string) {
        if (streaming) {
            message.warning('当前正在流式生成，先等它结束')
            return
        }
        selectKnowledgeBase(kbId)
    }

    async function handleSelectSession(sessionId: string) {
        if (streaming && sessionId !== activeSessionId) {
            message.warning('当前正在流式生成，暂时不能切换会话')
            return
        }
        setActiveSessionId(sessionId)
        const target = sessions.find((item) => item.session_id === sessionId)
        if (target && !target.loaded) {
            try {
                await loadSessionDetail(sessionId)
            } catch (err: any) {
                message.error(err?.message || '加载会话详情失败')
            }
        }
    }

    async function handleDeleteSession(sessionId: string) {
        if (streaming && sessionId === activeSessionId) {
            message.warning('当前正在流式生成，不能删除这个会话')
            return
        }
        try {
            await deleteChatSession(sessionId)
            const remaining = sessions.filter((item) => item.session_id !== sessionId)
            setSessions(sortSessions(remaining))
            if (activeSessionId === sessionId) {
                const nextSessionId = remaining[0]?.session_id || null
                setActiveSessionId(nextSessionId)
                if (nextSessionId) {
                    await loadSessionDetail(nextSessionId)
                }
            }
        } catch (err: any) {
            message.error(err?.message || '删除会话失败')
        }
    }

    async function handleViewCitation(citationId: string) {
        setCitationDrawerOpen(true)
        setCitationLoading(true)
        try {
            setCitationView(await getCitationView(citationId))
        } catch (err: any) {
            message.error(err?.message || '加载引用失败')
        } finally {
            setCitationLoading(false)
        }
    }

    async function handleOpenCitation(citation: CitationItem) {
        try {
            const target = await getCitationOpenTarget(citation.citation_id)
            window.open(resolveTargetUrl(target.url), '_blank', 'noopener,noreferrer')
        } catch (err: any) {
            message.error(err?.message || '打开原文失败')
        }
    }

    async function handleSend() {
        if (!user?.user_id || !currentKnowledgeBaseId) return
        const query = inputValue.trim()
        if (!query || streaming) return

        const requestId = `req_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
        const optimisticUserId = `temp_user_${requestId}`
        const optimisticAssistantId = `temp_assistant_${requestId}`
        const baseTimestamp = Date.now()
        const optimisticMessages: UiMessage[] = [
            ...currentMessages,
            {
                id: optimisticUserId,
                role: 'user',
                content: query,
                requestId,
                status: 'completed',
                timestamp: baseTimestamp,
            },
            {
                id: optimisticAssistantId,
                role: 'assistant',
                content: '',
                requestId,
                status: 'streaming',
                timestamp: baseTimestamp + 1,
            },
        ]

        setStreaming(true)
        setInputValue('')
        persistDraft('')

        if (activeSessionId) {
            const currentSession = activeConversation
            if (!currentSession) {
                setStreaming(false)
                return
            }
            setSessions((prev) => upsertSession(prev, { ...currentSession, messages: optimisticMessages, loaded: true }))

            let realUserId = optimisticUserId
            let realAssistantId = optimisticAssistantId
            try {
                await chatSessionMessageStream(
                    activeSessionId,
                    { query, request_id: requestId },
                    {
                        onMetadata: (payload) => {
                            realUserId = payload.user_message_id || realUserId
                            realAssistantId = payload.assistant_message_id || realAssistantId
                            if (payload.session) {
                                setSessions((prev) => {
                                    const baseSession =
                                        prev.find((item) => item.session_id === activeSessionId) || currentSession
                                    return upsertSession(prev, {
                                        ...baseSession,
                                        ...payload.session,
                                        messages: optimisticMessages.map((item) => {
                                            if (item.id === optimisticUserId) return { ...item, id: realUserId }
                                            if (item.id === optimisticAssistantId) return { ...item, id: realAssistantId }
                                            return item
                                        }),
                                        loaded: true,
                                    })
                                })
                            }
                        },
                        onToken: (token) => {
                            setSessions((prev) =>
                                prev.map((item) =>
                                    item.session_id === activeSessionId
                                        ? {
                                            ...item,
                                            messages: item.messages.map((msg) =>
                                                msg.id === realAssistantId || msg.id === optimisticAssistantId
                                                    ? { ...msg, id: realAssistantId, content: msg.content + token }
                                                    : msg
                                            ),
                                        }
                                        : item
                                )
                            )
                        },
                        onDone: async () => {
                            await loadSessionDetail(activeSessionId)
                        },
                        onError: (errMsg) => {
                            setSessions((prev) =>
                                prev.map((item) =>
                                    item.session_id === activeSessionId
                                        ? {
                                            ...item,
                                            messages: item.messages.map((msg) =>
                                                msg.id === realAssistantId || msg.id === optimisticAssistantId
                                                    ? { ...msg, id: realAssistantId, status: 'error', content: msg.content || errMsg }
                                                    : msg
                                            ),
                                        }
                                        : item
                                )
                            )
                        },
                    }
                )
            } catch (err: any) {
                message.error(err?.message || '发送失败')
            } finally {
                setStreaming(false)
            }
            return
        }

        setDraftMessages(optimisticMessages)
        let createdSessionId = ''
        let realUserId = optimisticUserId
        let realAssistantId = optimisticAssistantId

        try {
            await chatCompletionStream(
                { kb_id: currentKnowledgeBaseId, query, request_id: requestId },
                {
                    onMetadata: (payload) => {
                        createdSessionId = payload.session_id
                        realUserId = payload.user_message_id || realUserId
                        realAssistantId = payload.assistant_message_id || realAssistantId
                        const summary =
                            payload.session ||
                            buildFallbackSession(createdSessionId, currentKnowledgeBaseId, currentKnowledgeBase?.name || null, query)
                        const mappedMessages = optimisticMessages.map((item) => {
                            if (item.id === optimisticUserId) return { ...item, id: realUserId }
                            if (item.id === optimisticAssistantId) return { ...item, id: realAssistantId }
                            return item
                        })
                        setSessions((prev) =>
                            upsertSession(prev, {
                                ...summary,
                                messages: mappedMessages,
                                loaded: true,
                            })
                        )
                        setActiveSessionId(createdSessionId)
                        setDraftMessages([])
                    },
                    onToken: (token) => {
                        if (!createdSessionId) {
                            setDraftMessages((prev) =>
                                prev.map((msg) =>
                                    msg.id === optimisticAssistantId ? { ...msg, content: msg.content + token } : msg
                                )
                            )
                            return
                        }
                        setSessions((prev) =>
                            prev.map((item) =>
                                item.session_id === createdSessionId
                                    ? {
                                        ...item,
                                        messages: item.messages.map((msg) =>
                                            msg.id === realAssistantId || msg.id === optimisticAssistantId
                                                ? { ...msg, id: realAssistantId, content: msg.content + token }
                                                : msg
                                        ),
                                    }
                                    : item
                            )
                        )
                    },
                    onDone: async (payload) => {
                        if (payload.session_id) {
                            await loadSessionDetail(payload.session_id)
                        }
                    },
                    onError: (errMsg) => {
                        if (!createdSessionId) {
                            setDraftMessages((prev) =>
                                prev.map((msg) =>
                                    msg.id === optimisticAssistantId ? { ...msg, status: 'error', content: errMsg } : msg
                                )
                            )
                            return
                        }
                        setSessions((prev) =>
                            prev.map((item) =>
                                item.session_id === createdSessionId
                                    ? {
                                        ...item,
                                        messages: item.messages.map((msg) =>
                                            msg.id === realAssistantId || msg.id === optimisticAssistantId
                                                ? { ...msg, id: realAssistantId, status: 'error', content: msg.content || errMsg }
                                                : msg
                                        ),
                                    }
                                    : item
                            )
                        )
                    },
                }
            )
        } catch (err: any) {
            message.error(err?.message || '发送失败')
        } finally {
            setStreaming(false)
        }
    }

    async function handleLogout() {
        await logout()
        router.replace('/login')
    }

    return (
        <Layout style={{ minHeight: '100vh' }}>
            <Sider width={320} theme="light" style={{ borderRight: '1px solid #f0f0f0', padding: 16 }}>
                <Space direction="vertical" size={16} style={{ width: '100%' }}>
                    <div>
                        <Typography.Title level={4} style={{ marginBottom: 4 }}>
                            聊天工作台
                        </Typography.Title>
                        <Typography.Text type="secondary">
                            {user?.display_name || user?.email}
                        </Typography.Text>
                    </div>
                    <Select
                        value={currentKnowledgeBaseId || undefined}
                        onChange={handleSwitchKnowledgeBase}
                        disabled={streaming}
                        options={knowledgeBases.map((kb) => ({
                            value: kb.kb_id,
                            label: `${kb.name}${kb.visibility === 'system' ? '（系统）' : ''}`,
                        }))}
                    />
                    <Button onClick={() => setActiveSessionId(null)} disabled={streaming}>
                        新建对话
                    </Button>
                    <List
                        bordered
                        loading={loadingSessions}
                        dataSource={sessions}
                        locale={{ emptyText: <Empty description="当前知识库还没有会话" /> }}
                        renderItem={(item) => (
                            <List.Item
                                actions={[
                                    <Button
                                        key="delete"
                                        type="link"
                                        danger
                                        onClick={() => void handleDeleteSession(item.session_id)}
                                    >
                                        删除
                                    </Button>,
                                ]}
                                style={{
                                    cursor: 'pointer',
                                    background: item.session_id === activeSessionId ? '#f5f5f5' : undefined,
                                }}
                                onClick={() => void handleSelectSession(item.session_id)}
                            >
                                <List.Item.Meta
                                    title={item.title}
                                    description={
                                        <Space direction="vertical" size={0}>
                                            <Typography.Text type="secondary">{item.preview || '空白会话'}</Typography.Text>
                                            <Typography.Text type="secondary">
                                                {new Date(item.updated_at).toLocaleString('zh-CN')}
                                            </Typography.Text>
                                        </Space>
                                    }
                                />
                            </List.Item>
                        )}
                    />
                </Space>
            </Sider>
            <Layout>
                <Header
                    style={{
                        background: '#fff',
                        borderBottom: '1px solid #f0f0f0',
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'center',
                        paddingInline: 24,
                    }}
                >
                    <div>
                        <Typography.Title level={4} style={{ margin: 0 }}>
                            {currentKnowledgeBase?.name || '未选择知识库'}
                        </Typography.Title>
                        <Typography.Text type="secondary">
                            {currentKnowledgeBase?.visibility === 'system' ? '系统共享知识库' : '私有知识库'}
                        </Typography.Text>
                    </div>
                    <Space>
                        <Button onClick={() => router.push('/knowledge')}>知识库管理</Button>
                        <Button icon={<LogoutOutlined />} onClick={() => void handleLogout()}>
                            退出登录
                        </Button>
                    </Space>
                </Header>
                <Content style={{ padding: 24, display: 'flex', flexDirection: 'column', gap: 16 }}>
                    <div
                        style={{
                            flex: 1,
                            minHeight: 0,
                            background: '#fff',
                            border: '1px solid #f0f0f0',
                            borderRadius: 8,
                            padding: 16,
                            overflow: 'auto',
                        }}
                    >
                        {loadingSessions ? (
                            <div style={{ minHeight: 320, display: 'grid', placeItems: 'center' }}>
                                <Spin size="large" />
                            </div>
                        ) : currentMessages.length === 0 ? (
                            <Empty description="从当前知识库开始提问" />
                        ) : (
                            <Space direction="vertical" size={16} style={{ width: '100%' }}>
                                {sortMessages(currentMessages).map((msg) => (
                                    <div
                                        key={msg.id}
                                        style={{
                                            alignSelf: msg.role === 'user' ? 'flex-end' : 'stretch',
                                            background: msg.role === 'user' ? '#1677ff' : '#fafafa',
                                            color: msg.role === 'user' ? '#fff' : '#111',
                                            borderRadius: 12,
                                            padding: 16,
                                        }}
                                    >
                                        {msg.role === 'assistant' ? (
                                            <>
                                                <div dangerouslySetInnerHTML={{ __html: md.render(msg.content || (msg.status === 'streaming' ? '...' : '')) }} />
                                                {msg.citations?.length ? (
                                                    <Space direction="vertical" size={8} style={{ width: '100%', marginTop: 12 }}>
                                                        {msg.citations.map((citation) => (
                                                            <div
                                                                key={citation.citation_id}
                                                                style={{ border: '1px solid #f0f0f0', borderRadius: 8, padding: 12 }}
                                                            >
                                                                <Typography.Text strong>{citation.source.title}</Typography.Text>
                                                                <Typography.Paragraph style={{ marginTop: 8, marginBottom: 8 }}>
                                                                    {citation.snippet}
                                                                </Typography.Paragraph>
                                                                <Space>
                                                                    <Button size="small" onClick={() => void handleViewCitation(citation.citation_id)}>
                                                                        查看摘录
                                                                    </Button>
                                                                    <Button size="small" onClick={() => void handleOpenCitation(citation)}>
                                                                        打开原文
                                                                    </Button>
                                                                </Space>
                                                            </div>
                                                        ))}
                                                    </Space>
                                                ) : null}
                                            </>
                                        ) : (
                                            <Typography.Text style={{ color: '#fff' }}>{msg.content}</Typography.Text>
                                        )}
                                    </div>
                                ))}
                            </Space>
                        )}
                    </div>
                    <div style={{ background: '#fff', border: '1px solid #f0f0f0', borderRadius: 8, padding: 16 }}>
                        <Space direction="vertical" size={12} style={{ width: '100%' }}>
                            <Typography.Text type="secondary">
                                {streaming ? '正在生成回答，暂时不能切换知识库或会话。' : '当前提问会绑定到所选知识库。'}
                            </Typography.Text>
                            <TextArea
                                value={inputValue}
                                onChange={(event) => {
                                    setInputValue(event.target.value)
                                    persistDraft(event.target.value)
                                }}
                                onPressEnter={(event) => {
                                    if (!event.shiftKey) {
                                        event.preventDefault()
                                        void handleSend()
                                    }
                                }}
                                placeholder="输入问题，回车发送，Shift + Enter 换行"
                                autoSize={{ minRows: 3, maxRows: 8 }}
                                disabled={streaming || !currentKnowledgeBaseId}
                            />
                            <Space style={{ width: '100%', justifyContent: 'space-between' }}>
                                <Typography.Text type="secondary">
                                    {activeConversation ? `当前会话：${activeConversation.title}` : '新问题会自动创建会话'}
                                </Typography.Text>
                                <Button type="primary" onClick={() => void handleSend()} disabled={!inputValue.trim() || streaming || !currentKnowledgeBaseId}>
                                    发送
                                </Button>
                            </Space>
                        </Space>
                    </div>
                </Content>
            </Layout>
            <Drawer
                title="引用摘录"
                open={citationDrawerOpen}
                onClose={() => {
                    setCitationDrawerOpen(false)
                    setCitationView(null)
                }}
                width={560}
            >
                {citationLoading ? (
                    <div style={{ minHeight: 240, display: 'grid', placeItems: 'center' }}>
                        <Spin />
                    </div>
                ) : citationView ? (
                    <Typography.Paragraph style={{ whiteSpace: 'pre-wrap' }}>
                        {citationView.context_text}
                    </Typography.Paragraph>
                ) : (
                    <Empty description="暂无引用内容" />
                )}
            </Drawer>
        </Layout>
    )
}


export default function ChatPage() {
    return (
        <AuthGuard>
            <ChatWorkspace />
        </AuthGuard>
    )
}
