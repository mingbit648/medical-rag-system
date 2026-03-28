import {
    buildFallbackSessionSummary,
    remapOptimisticMessages,
    resolveInitialActiveView,
    sortChatMessages,
    upsertConversation,
    type ChatMessage,
    type ConversationRecord,
} from '@/lib/chat/sessionState'


function makeConversation(sessionId: string, updatedAt: string): ConversationRecord {
    return {
        session_id: sessionId,
        kb_id: 'kb_1',
        kb_name: '测试知识库',
        title: sessionId,
        status: 'active',
        preview: '',
        message_count: 2,
        created_at: updatedAt,
        updated_at: updatedAt,
        last_active_at: updatedAt,
        active_summary_id: null,
        messages: [],
        loaded: true,
    }
}


describe('chat session state helpers', () => {
    test('resolveInitialActiveView falls back to draft when no persisted sessions exist', () => {
        expect(resolveInitialActiveView([], 's_missing')).toEqual({ kind: 'draft' })
    })

    test('resolveInitialActiveView prefers stored active session when available', () => {
        const conversations = [
            makeConversation('s_old', '2026-03-14T10:00:00.000Z'),
            makeConversation('s_keep', '2026-03-14T11:00:00.000Z'),
        ]

        expect(resolveInitialActiveView(conversations, 's_keep')).toEqual({ kind: 'session', sessionId: 's_keep' })
    })

    test('remapOptimisticMessages promotes temp ids into persisted ids', () => {
        const optimistic: ChatMessage[] = [
            { id: 'temp_user_req_1', role: 'user', content: '你好', timestamp: 1, status: 'completed' },
            { id: 'temp_assistant_req_1', role: 'assistant', content: '', timestamp: 2, status: 'streaming' },
        ]

        expect(
            remapOptimisticMessages(optimistic, {
                optimisticUserId: 'temp_user_req_1',
                optimisticAssistantId: 'temp_assistant_req_1',
                userMessageId: 'msg_user_real',
                assistantMessageId: 'msg_assistant_real',
                assistantContent: '已生成',
                assistantStatus: 'completed',
            })
        ).toEqual([
            { id: 'msg_user_real', role: 'user', content: '你好', timestamp: 1, status: 'completed' },
            {
                id: 'msg_assistant_real',
                role: 'assistant',
                content: '已生成',
                timestamp: 2,
                status: 'completed',
                citations: undefined,
            },
        ])
    })

    test('upsertConversation inserts new sessions and keeps latest updated session first', () => {
        const older = makeConversation('s_old', '2026-03-14T10:00:00.000Z')
        const newer = makeConversation('s_new', '2026-03-14T12:00:00.000Z')

        const result = upsertConversation([older], newer)

        expect(result.map((item) => item.session_id)).toEqual(['s_new', 's_old'])
    })

    test('buildFallbackSessionSummary derives a persisted summary from the first query', () => {
        const summary = buildFallbackSessionSummary('s_created', '公司拖欠工资怎么办？', Date.UTC(2026, 2, 15, 0, 0, 0), 'kb_1')

        expect(summary).toMatchObject({
            session_id: 's_created',
            kb_id: 'kb_1',
            title: '公司拖欠工资怎么办？',
            preview: '公司拖欠工资怎么办？',
            message_count: 2,
            status: 'active',
        })
    })

    test('remapOptimisticMessages only rewrites the current optimistic pair', () => {
        const messages: ChatMessage[] = [
            { id: 'temp_user_old', role: 'user', content: '旧失败问题', timestamp: 1, status: 'completed' },
            { id: 'temp_assistant_old', role: 'assistant', content: '旧失败回答', timestamp: 2, status: 'error' },
            { id: 'temp_user_current', role: 'user', content: '当前问题', timestamp: 3, status: 'completed' },
            { id: 'temp_assistant_current', role: 'assistant', content: '', timestamp: 4, status: 'streaming' },
        ]

        expect(
            remapOptimisticMessages(messages, {
                optimisticUserId: 'temp_user_current',
                optimisticAssistantId: 'temp_assistant_current',
                userMessageId: 'msg_user_current',
                assistantMessageId: 'msg_assistant_current',
                assistantContent: '当前回答',
                assistantStatus: 'completed',
            }).map((item) => item.id)
        ).toEqual([
            'temp_user_old',
            'temp_assistant_old',
            'msg_user_current',
            'msg_assistant_current',
        ])
    })

    test('sortChatMessages keeps the user message first within a turn', () => {
        const messages: ChatMessage[] = [
            { id: 'msg_assistant', role: 'assistant', content: '回复', timestamp: 200, requestId: 'req_1', status: 'completed' },
            { id: 'msg_user', role: 'user', content: '问题', timestamp: 200, requestId: 'req_1', status: 'completed' },
        ]

        expect(sortChatMessages(messages).map((item) => item.id)).toEqual(['msg_user', 'msg_assistant'])
    })
})
