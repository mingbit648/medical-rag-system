import { apiClient } from './client'

export interface ApiEnvelope<T> {
    code: number
    message: string
    data: T
    trace_id: string
}

export interface DocImportResult {
    doc_id: string
    title: string
    doc_type: string
    status: string
}

export interface DocIndexResult {
    doc_id: string
    status: string
    chunks: number
    chunk: {
        size: number
        overlap: number
    }
}

export interface DocStatusResult {
    doc_id: string
    title: string
    doc_type: string
    parse_status: string
    chunks: number
    created_at: string
}

export interface CitationItem {
    citation_id: string
    chunk_id: string
    doc_id: string
    source: {
        title: string
        url_or_file: string
    }
    location: {
        section?: string | null
        article_no?: string | null
    }
    snippet: string
    scores: {
        bm25: number
        vector: number
        rrf: number
        rerank: number
    }
}

export interface ChatCompletionData {
    session_id: string
    answer_md: string
    citations: CitationItem[]
}

export interface ChatHistoryMessage {
    msg_id: string
    session_id: string
    role: 'user' | 'assistant' | 'system' | string
    content: string
    created_at: string
}

export interface CitationViewData {
    doc_id: string
    doc_type: string
    context_text: string
    highlight: {
        method: 'offset' | 'whole_chunk'
        start?: number
        end?: number
        chunk_text?: string
        reason?: string
    }
    fallback: any
}

export interface ChatCompletionRequest {
    session_id?: string
    query: string
    topn?: {
        bm25: number
        vector: number
    }
    fusion?: {
        method: string
        k: number
    }
    rerank?: {
        topk: number
        topm: number
    }
    llm?: {
        provider: string
        model: string
        temperature: number
        base_url?: string
        api_key?: string
    }
}

export interface StreamHandlers {
    onToken?: (token: string) => void
    onDone?: (payload: { session_id: string; citations: CitationItem[]; trace_id: string }) => void
    onError?: (message: string) => void
}

export interface ExperimentCaseInput {
    query: string
    relevant_chunk_ids?: string[]
    relevant_doc_ids?: string[]
}

export interface ExperimentRunResult {
    run_id: string
    mode: string
    metrics: {
        baseline: {
            'recall@5': number
            mrr: number
        }
        improved: {
            'recall@5': number
            mrr: number
        }
        total_cases: number
        cases: Array<Record<string, any>>
    }
}

function unwrap<T>(envelope: ApiEnvelope<T>): T {
    if (envelope.code !== 0) {
        throw new Error(envelope.message || '请求失败')
    }
    return envelope.data
}

function withDefaults(request: ChatCompletionRequest): ChatCompletionRequest {
    return {
        ...request,
        topn: request.topn || { bm25: 50, vector: 50 },
        fusion: request.fusion || { method: 'rrf', k: 60 },
        rerank: request.rerank || { topk: 30, topm: 8 },
        llm: request.llm || { provider: 'deepseek', model: 'deepseek-chat', temperature: 0.2 },
    }
}

export async function importDocument(file: File, sourceUrl?: string, docType?: string): Promise<DocImportResult> {
    const formData = new FormData()
    formData.append('file', file)
    if (sourceUrl) formData.append('source_url', sourceUrl)
    if (docType) formData.append('doc_type', docType)

    const response = await fetch(`${apiClient['baseUrl']}/api/v1/docs/import`, {
        method: 'POST',
        body: formData,
    })

    if (!response.ok) {
        const detail = await response.text()
        throw new Error(detail || '文档导入失败')
    }

    const envelope = await response.json() as ApiEnvelope<DocImportResult>
    return unwrap(envelope)
}

export async function indexDocument(docId: string, chunkSize = 800, overlap = 200): Promise<DocIndexResult> {
    const envelope = await apiClient.post<ApiEnvelope<DocIndexResult>>(`/api/v1/docs/${docId}/index`, {
        chunk: { size: chunkSize, overlap },
        bm25: { enabled: true },
        vector: { enabled: true, embed_model: 'sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2' },
    })
    return unwrap(envelope)
}

export async function getDocumentStatus(docId: string): Promise<DocStatusResult> {
    const envelope = await apiClient.get<ApiEnvelope<DocStatusResult>>(`/api/v1/docs/${docId}/status`)
    return unwrap(envelope)
}

export async function chatCompletion(request: ChatCompletionRequest): Promise<ChatCompletionData> {
    const envelope = await apiClient.post<ApiEnvelope<ChatCompletionData>>('/api/v1/chat/completions', withDefaults(request))
    return unwrap(envelope)
}

export async function chatCompletionStream(request: ChatCompletionRequest, handlers: StreamHandlers = {}): Promise<void> {
    const response = await fetch(`${apiClient['baseUrl']}/api/v1/chat/completions:stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(withDefaults(request)),
    })

    if (!response.ok || !response.body) {
        const text = await response.text()
        throw new Error(text || '流式请求失败')
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
        const { value, done } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })

        const events = buffer.split('\n\n')
        buffer = events.pop() || ''

        for (const block of events) {
            const lines = block.split('\n')
            const eventLine = lines.find((line) => line.startsWith('event:'))
            const dataLine = lines.find((line) => line.startsWith('data:'))
            if (!eventLine || !dataLine) continue

            const event = eventLine.replace('event:', '').trim()
            const data = dataLine.replace('data:', '').trim()

            if (event === 'token') {
                try {
                    const parsedToken = JSON.parse(data)
                    handlers.onToken?.(parsedToken)
                } catch {
                    handlers.onToken?.(data)
                }
            } else if (event === 'done') {
                handlers.onDone?.(JSON.parse(data))
            } else if (event === 'error') {
                try {
                    const payload = JSON.parse(data)
                    handlers.onError?.(payload.message || 'stream error')
                } catch {
                    handlers.onError?.(data || 'stream error')
                }
            }
        }
    }
}

export async function retrieveDebug(request: Omit<ChatCompletionRequest, 'session_id' | 'llm'>): Promise<any> {
    const envelope = await apiClient.post<ApiEnvelope<any>>('/api/v1/retrieve/debug', withDefaults({ query: request.query, topn: request.topn, fusion: request.fusion, rerank: request.rerank }))
    return unwrap(envelope)
}

export async function getCitationView(citationId: string, contextBefore = 400, contextAfter = 400): Promise<CitationViewData> {
    const envelope = await apiClient.get<ApiEnvelope<CitationViewData>>(`/api/v1/citations/${citationId}/view`, {
        context_before: contextBefore,
        context_after: contextAfter,
    })
    return unwrap(envelope)
}

export async function getChatHistory(sessionId: string, limit = 50): Promise<{ session_id: string; messages: ChatHistoryMessage[] }> {
    const envelope = await apiClient.get<ApiEnvelope<{ session_id: string; messages: ChatHistoryMessage[] }>>(
        `/api/v1/chat/history/${sessionId}`,
        { limit }
    )
    return unwrap(envelope)
}

export async function runExperiment(cases: ExperimentCaseInput[]): Promise<ExperimentRunResult> {
    const envelope = await apiClient.post<ApiEnvelope<ExperimentRunResult>>('/api/v1/experiments/run', {
        dataset: cases,
        topn: { bm25: 50, vector: 50 },
        fusion: { method: 'rrf', k: 60 },
        rerank: { topk: 30, topm: 8 },
    })
    return unwrap(envelope)
}

export async function listRuns(limit = 20): Promise<{ items: Array<Record<string, any>> }> {
    const envelope = await apiClient.get<ApiEnvelope<{ items: Array<Record<string, any>> }>>('/api/v1/experiments/runs', { limit })
    return unwrap(envelope)
}
