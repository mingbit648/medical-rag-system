'use client'

import { useMemo, useState } from 'react'
import AuthGuard from '@/components/AuthGuard'
import { useAppSession } from '@/lib/session/AppSessionProvider'
import {
    chatCompletion,
    chatCompletionStream,
    getChatHistory,
    getCitationView,
    getDocumentStatus,
    importDocument,
    indexDocument,
    runExperiment,
    type ChatHistoryMessage,
    type CitationItem,
    type CitationViewData,
} from '@/lib/api/legalRag'

type HighlightPieces = {
    before: string
    hit: string
    after: string
}

function toHighlightPieces(view: CitationViewData | null): HighlightPieces | null {
    if (!view) return null
    if (view.highlight.method === 'offset' && typeof view.highlight.start === 'number' && typeof view.highlight.end === 'number') {
        const start = Math.max(0, Math.min(view.highlight.start, view.context_text.length))
        const end = Math.max(start, Math.min(view.highlight.end, view.context_text.length))
        return {
            before: view.context_text.slice(0, start),
            hit: view.context_text.slice(start, end),
            after: view.context_text.slice(end),
        }
    }
    if (view.highlight.method === 'whole_chunk' && view.highlight.chunk_text) {
        return {
            before: '',
            hit: view.highlight.chunk_text,
            after: '',
        }
    }
    return {
        before: '',
        hit: view.context_text,
        after: '',
    }
}

export default function LegalShellPage() {
    const { currentKnowledgeBase, currentKnowledgeBaseId } = useAppSession()
    const [file, setFile] = useState<File | null>(null)
    const [docId, setDocId] = useState('')
    const [query, setQuery] = useState('公司拖欠工资怎么办？')
    const [sessionId, setSessionId] = useState('')
    const [answer, setAnswer] = useState('')
    const [citations, setCitations] = useState<CitationItem[]>([])
    const [citationView, setCitationView] = useState<CitationViewData | null>(null)
    const [history, setHistory] = useState<ChatHistoryMessage[]>([])
    const [expResult, setExpResult] = useState<string>('')
    const [statusText, setStatusText] = useState('未开始')
    const [loading, setLoading] = useState(false)
    const [streaming, setStreaming] = useState(false)

    const canAsk = useMemo(() => Boolean(query.trim()) && Boolean(sessionId || currentKnowledgeBaseId), [query, sessionId, currentKnowledgeBaseId])
    const highlight = useMemo(() => toHighlightPieces(citationView), [citationView])

    async function handleImportAndIndex() {
        if (!file) {
            setStatusText('请先选择 PDF/HTML/TXT 文件')
            return
        }
        if (!currentKnowledgeBaseId) {
            setStatusText('请先选择当前知识库')
            return
        }
        setLoading(true)
        try {
            setStatusText('导入中...')
            const imported = await importDocument(file, { kbId: currentKnowledgeBaseId })
            setDocId(imported.doc_id)

            setStatusText('提交索引任务中...')
            await indexDocument(imported.doc_id)

            const status = await getDocumentStatus(imported.doc_id)
            setStatusText(`索引任务已提交: ${status.title}（status=${status.parse_status}）`)
        } catch (error: any) {
            setStatusText(`失败: ${error.message || '未知错误'}`)
        } finally {
            setLoading(false)
        }
    }

    async function handleAskBlocking() {
        if (!canAsk) {
            setStatusText('请先选择知识库后再提问')
            return
        }
        setLoading(true)
        try {
            const data = await chatCompletion({
                session_id: sessionId || undefined,
                kb_id: sessionId ? undefined : currentKnowledgeBaseId || undefined,
                query,
            })
            setSessionId(data.session_id)
            setAnswer(data.answer_md)
            setCitations(data.citations)
            setStatusText(`问答完成，返回引用 ${data.citations.length} 条`)
        } catch (error: any) {
            setStatusText(`问答失败: ${error.message || '未知错误'}`)
        } finally {
            setLoading(false)
        }
    }

    async function handleAskStreaming() {
        if (!canAsk || streaming) {
            if (!canAsk) {
                setStatusText('请先选择知识库后再提问')
            }
            return
        }
        setStreaming(true)
        setAnswer('')
        setCitations([])
        setStatusText('流式生成中...')

        try {
            await chatCompletionStream(
                {
                    session_id: sessionId || undefined,
                    kb_id: sessionId ? undefined : currentKnowledgeBaseId || undefined,
                    query,
                },
                {
                    onToken: (token) => {
                        setAnswer((prev) => prev + token)
                    },
                    onDone: (payload) => {
                        setSessionId(payload.session_id)
                        setCitations(payload.citations)
                        setStatusText(`流式完成，返回引用 ${payload.citations.length} 条`)
                    },
                    onError: (message) => {
                        setStatusText(`流式失败: ${message}`)
                    },
                }
            )
        } catch (error: any) {
            setStatusText(`流式失败: ${error.message || '未知错误'}`)
        } finally {
            setStreaming(false)
        }
    }

    async function handleViewCitation(citationId: string) {
        try {
            const data = await getCitationView(citationId)
            setCitationView(data)
        } catch (error: any) {
            setStatusText(`查看引用失败: ${error.message || '未知错误'}`)
        }
    }

    async function handleLoadHistory() {
        if (!sessionId) {
            setStatusText('暂无 session_id，请先提问')
            return
        }
        try {
            const data = await getChatHistory(sessionId)
            setHistory(data.messages)
            setStatusText(`历史加载完成，共 ${data.messages.length} 条消息`)
        } catch (error: any) {
            setStatusText(`历史加载失败: ${error.message || '未知错误'}`)
        }
    }

    async function handleRunExperiment() {
        if (!currentKnowledgeBaseId) {
            setStatusText('请先选择当前知识库')
            return
        }
        if (!docId) {
            setStatusText('请先完成文档导入与建索引')
            return
        }
        try {
            const res = await runExperiment(currentKnowledgeBaseId, [
                {
                    query: query || '公司拖欠工资怎么办？',
                    relevant_doc_ids: [docId],
                },
            ])
            setExpResult(JSON.stringify(res.metrics, null, 2))
            setStatusText(`实验运行完成，run_id=${res.run_id}`)
        } catch (error: any) {
            setStatusText(`实验运行失败: ${error.message || '未知错误'}`)
        }
    }

    return (
        <AuthGuard>
            <main className="min-h-screen bg-gray-50 p-6">
                <div className="mx-auto max-w-5xl space-y-4">
                    <h1 className="text-2xl font-bold">法律 RAG 联调页</h1>
                    <p className="text-sm text-gray-600">
                        目标：跑通导入 {'->'} 建索引 {'->'} 问答（阻塞/流式） {'->'} 引用高亮查看 {'->'} 实验评测。
                    </p>
                    <div className="text-sm text-gray-700">
                        当前知识库: {currentKnowledgeBase?.name || '未选择'}
                    </div>

                    <section className="rounded-lg border bg-white p-4 space-y-3">
                        <h2 className="font-semibold">1. 文档导入与建索引</h2>
                        <input
                            type="file"
                            accept=".pdf,.html,.htm,.txt"
                            onChange={(e) => setFile(e.target.files?.[0] || null)}
                        />
                        <button
                            className="px-3 py-2 rounded bg-blue-600 text-white disabled:opacity-40"
                            onClick={handleImportAndIndex}
                            disabled={!file || loading || !currentKnowledgeBaseId}
                        >
                            导入并建索引
                        </button>
                        <div className="text-sm text-gray-700">doc_id: {docId || '-'}</div>
                    </section>

                    <section className="rounded-lg border bg-white p-4 space-y-3">
                        <h2 className="font-semibold">2. 问答（阻塞/流式）</h2>
                        <textarea className="w-full border rounded p-2 h-28" value={query} onChange={(e) => setQuery(e.target.value)} />
                        <div className="flex gap-2">
                            <button
                                className="px-3 py-2 rounded bg-emerald-600 text-white disabled:opacity-40"
                                onClick={handleAskBlocking}
                                disabled={!canAsk || loading || streaming}
                            >
                                阻塞式提问
                            </button>
                            <button
                                className="px-3 py-2 rounded bg-violet-600 text-white disabled:opacity-40"
                                onClick={handleAskStreaming}
                                disabled={!canAsk || loading || streaming}
                            >
                                流式提问
                            </button>
                            <button className="px-3 py-2 rounded border" onClick={handleLoadHistory} disabled={!sessionId}>
                                加载会话历史
                            </button>
                        </div>
                        <div className="text-sm text-gray-700">session_id: {sessionId || '-'}</div>
                        <pre className="whitespace-pre-wrap text-sm bg-gray-50 p-3 rounded border">{answer || '暂无回答'}</pre>
                    </section>

                    <section className="rounded-lg border bg-white p-4 space-y-3">
                        <h2 className="font-semibold">3. 引用查看（高亮）</h2>
                        {citations.length === 0 && <div className="text-sm text-gray-500">暂无引用</div>}
                        {citations.map((item) => (
                            <div key={item.citation_id} className="border rounded p-3 bg-gray-50 space-y-2">
                                <div className="text-sm font-medium">{item.source.title}</div>
                                <div className="text-sm text-gray-700">{item.snippet}</div>
                                <button className="px-2 py-1 rounded border" onClick={() => handleViewCitation(item.citation_id)}>
                                    查看原文上下文
                                </button>
                            </div>
                        ))}
                        <div className="text-sm bg-gray-50 p-3 rounded border whitespace-pre-wrap">
                            {!highlight && '尚未查看引用上下文'}
                            {highlight && (
                                <>
                                    {highlight.before}
                                    <mark className="bg-yellow-300">{highlight.hit || '(空命中片段)'}</mark>
                                    {highlight.after}
                                </>
                            )}
                        </div>
                    </section>

                    <section className="rounded-lg border bg-white p-4 space-y-3">
                        <h2 className="font-semibold">4. 实验评测（Recall@5 / MRR）</h2>
                        <button className="px-3 py-2 rounded border" onClick={handleRunExperiment} disabled={!currentKnowledgeBaseId}>
                            运行最小实验
                        </button>
                        <pre className="whitespace-pre-wrap text-sm bg-gray-50 p-3 rounded border">{expResult || '暂无实验结果'}</pre>
                    </section>

                    <section className="rounded-lg border bg-white p-4 space-y-3">
                        <h2 className="font-semibold">5. 会话历史</h2>
                        {history.length === 0 && <div className="text-sm text-gray-500">暂无历史消息</div>}
                        {history.map((msg) => (
                            <div key={msg.msg_id} className="rounded border p-2">
                                <div className="text-xs text-gray-500">{msg.role} | {msg.created_at}</div>
                                <div className="text-sm whitespace-pre-wrap">{msg.content}</div>
                            </div>
                        ))}
                    </section>

                    <div className="text-sm text-gray-700">状态: {statusText}</div>
                </div>
            </main>
        </AuthGuard>
    )
}
