import type { CitationItem, ChatSessionSummary } from '@/lib/api/legalRag'

export const DRAFT_VIEW_KEY = '__draft__'

export interface ChatMessage {
    id: string
    role: 'user' | 'assistant'
    content: string
    citations?: CitationItem[]
    timestamp: number
    status: 'streaming' | 'completed' | 'error'
}

export interface ConversationRecord extends ChatSessionSummary {
    messages: ChatMessage[]
    loaded: boolean
}

export interface DraftState {
    input: string
    messages: ChatMessage[]
}

export type ActiveView = { kind: 'draft' } | { kind: 'session'; sessionId: string }

function previewText(text: string, maxChars: number) {
    const normalized = (text || '').replace(/\s+/g, ' ').trim()
    return normalized.slice(0, maxChars)
}

export function sortConversations(items: ConversationRecord[]) {
    return [...items].sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime())
}

export function resolveInitialActiveView(conversations: ConversationRecord[], storedActive: string): ActiveView {
    if (storedActive && conversations.some((item) => item.session_id === storedActive)) {
        return { kind: 'session', sessionId: storedActive }
    }
    if (conversations.length > 0) {
        return { kind: 'session', sessionId: conversations[0].session_id }
    }
    return { kind: 'draft' }
}

export function buildFallbackSessionSummary(sessionId: string, query: string, timestamp: number): ChatSessionSummary {
    const iso = new Date(timestamp).toISOString()
    const preview = previewText(query, 80)
    return {
        session_id: sessionId,
        title: previewText(query, 28) || '新对话',
        status: 'active',
        preview,
        message_count: 2,
        created_at: iso,
        updated_at: iso,
        last_active_at: iso,
        active_summary_id: null,
    }
}

export function remapOptimisticMessages(
    messages: ChatMessage[],
    {
        optimisticUserId,
        optimisticAssistantId,
        userMessageId,
        assistantMessageId,
        assistantContent,
        citations,
        assistantStatus,
    }: {
        optimisticUserId?: string
        optimisticAssistantId?: string
        userMessageId?: string
        assistantMessageId?: string
        assistantContent?: string
        citations?: CitationItem[]
        assistantStatus?: ChatMessage['status']
    }
) {
    return messages.map((item) => {
        if (userMessageId && item.id === optimisticUserId) {
            return { ...item, id: userMessageId }
        }
        if (assistantMessageId && item.id === optimisticAssistantId) {
            return {
                ...item,
                id: assistantMessageId,
                content: assistantContent ?? item.content,
                citations: citations ?? item.citations,
                status: assistantStatus ?? item.status,
            }
        }
        return item
    })
}

export function upsertConversation(conversations: ConversationRecord[], nextConversation: ConversationRecord) {
    const exists = conversations.some((item) => item.session_id === nextConversation.session_id)
    const merged = exists
        ? conversations.map((item) => (item.session_id === nextConversation.session_id ? nextConversation : item))
        : [nextConversation, ...conversations]
    return sortConversations(merged)
}
