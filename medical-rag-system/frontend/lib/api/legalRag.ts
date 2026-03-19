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
    overwritten?: boolean
}

export interface DuplicateDocumentInfo extends DocStatusResult {
    original_file_name?: string | null
}

export interface ImportDocumentOptions {
    sourceUrl?: string
    docType?: string
    overwriteDocId?: string
}

export interface BatchImportProgress {
    total: number
    currentIndex: number
    fileName: string
    stage: 'awaiting_confirmation' | 'uploading' | 'indexing'
}

export interface BatchImportItemResult {
    fileName: string
    success: boolean
    doc_id?: string
    title?: string
    doc_type?: string
    status?: string
    chunks?: number
    skipped?: boolean
    overwritten?: boolean
    existingDocTitle?: string
    error?: string
}

export interface BatchImportResult {
    items: BatchImportItemResult[]
    total: number
    successCount: number
    failureCount: number
    skippedCount: number
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

export interface DocumentDetailChunk {
    chunk_id: string
    chunk_index: number
    chunk_text: string
    start_pos?: number | null
    end_pos?: number | null
    section?: string | null
    article_no?: string | null
    page_start?: number | null
    page_end?: number | null
    locator_json?: Record<string, any> | null
}

export interface DocumentDetail {
    doc_id: string
    title: string
    doc_type: string
    parse_status: string
    chunks: number
    created_at: string
    original_file_name?: string | null
    viewer_mode?: string | null
    download_url?: string | null
    text: string
    chunk_items: DocumentDetailChunk[]
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
        page?: number | null
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
    user_message_id?: string
    assistant_message_id?: string
    session?: ChatSessionSummary
}

export interface ChatHistoryMessage {
    msg_id: string
    message_id?: string
    session_id: string
    session_seq?: number
    role: 'user' | 'assistant' | 'system' | string
    content: string
    status?: 'streaming' | 'completed' | 'error' | string
    message_type?: string
    created_at: string
    updated_at?: string
    completed_at?: string | null
    citations?: CitationItem[]
    meta_json?: Record<string, any>
}

export interface ChatSessionSummary {
    session_id: string
    title: string
    status: 'active' | 'archived' | 'deleted' | string
    preview: string
    message_count: number
    created_at: string
    updated_at: string
    last_active_at: string
    active_summary_id?: string | null
}

export interface ChatSessionDetail {
    session: ChatSessionSummary
    messages: ChatHistoryMessage[]
    active_summary?: {
        snapshot_id: string
        from_seq: number
        to_seq: number
        summary_text: string
        meta_json?: Record<string, any>
    } | null
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

export interface CitationOpenTarget {
    doc_id: string
    title: string
    doc_type: string
    target_kind: 'pdf' | 'text_viewer'
    url: string
    page?: number | null
    segment_label?: string | null
    download_url?: string | null
    viewer_ready: boolean
}

export interface DocumentViewerContent {
    doc_id: string
    title: string
    doc_type: string
    viewer_mode: string
    download_url: string
    text: string
    highlight: {
        start: number
        end: number
    }
    citation_meta: {
        section?: string | null
        article_no?: string | null
        snippet: string
    }
}

export interface ChatCompletionRequest {
    session_id?: string
    request_id?: string
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
    onMetadata?: (payload: {
        session_id: string
        user_message_id?: string
        assistant_message_id?: string
        citations: CitationItem[]
        session?: ChatSessionSummary
    }) => void
    onDone?: (payload: {
        session_id: string
        user_message_id?: string
        assistant_message_id?: string
        citations: CitationItem[]
        session?: ChatSessionSummary
        trace_id: string
    }) => void
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

async function buildMultipartError(response: Response): Promise<Error> {
    const errorData = await response.json().catch(() => null)
    const detail = errorData?.detail
    const message =
        typeof detail === 'string'
            ? detail
            : detail?.message || errorData?.message || '文档导入失败'
    const error = new Error(message)
    ;(error as any).status = response.status
    if (detail && typeof detail === 'object' && typeof detail.code === 'string') {
        ;(error as any).code = detail.code
    }
    if (detail && typeof detail === 'object' && detail.existing_doc) {
        ;(error as any).existingDocument = detail.existing_doc as DuplicateDocumentInfo
    }
    return error
}

export async function importDocument(file: File, options: ImportDocumentOptions = {}): Promise<DocImportResult> {
    const formData = new FormData()
    formData.append('file', file)
    if (options.sourceUrl) formData.append('source_url', options.sourceUrl)
    if (options.docType) formData.append('doc_type', options.docType)
    if (options.overwriteDocId) formData.append('overwrite_doc_id', options.overwriteDocId)

    const response = await fetch(`${apiClient['baseUrl']}/api/v1/docs/import`, {
        method: 'POST',
        body: formData,
    })

    if (!response.ok) {
        throw await buildMultipartError(response)
    }

    const envelope = await response.json() as ApiEnvelope<DocImportResult>
    return unwrap(envelope)
}

export async function importDocuments(
    files: File[],
    options: {
        sourceUrl?: string
        docType?: string
        chunkSize?: number
        overlap?: number
        onProgress?: (progress: BatchImportProgress) => void
        onDuplicate?: (payload: {
            file: File
            currentIndex: number
            total: number
            existingDocument: DuplicateDocumentInfo
        }) => Promise<'overwrite' | 'skip'>
    } = {}
): Promise<BatchImportResult> {
    const normalizedFiles = files.filter((file): file is File => file instanceof File)
    const items: BatchImportItemResult[] = []

    for (const [index, file] of normalizedFiles.entries()) {
        try {
            options.onProgress?.({
                total: normalizedFiles.length,
                currentIndex: index + 1,
                fileName: file.name,
                stage: 'uploading',
            })
            let imported: DocImportResult
            try {
                imported = await importDocument(file, {
                    sourceUrl: options.sourceUrl,
                    docType: options.docType,
                })
            } catch (error: any) {
                const existingDocument = error?.existingDocument as DuplicateDocumentInfo | undefined
                const duplicateHandler = options.onDuplicate
                const canConfirm =
                    error?.status === 409 &&
                    error?.code === 'DOCUMENT_ALREADY_EXISTS' &&
                    existingDocument &&
                    duplicateHandler

                if (!canConfirm) {
                    throw error
                }

                options.onProgress?.({
                    total: normalizedFiles.length,
                    currentIndex: index + 1,
                    fileName: file.name,
                    stage: 'awaiting_confirmation',
                })
                const decision = await duplicateHandler({
                    file,
                    currentIndex: index + 1,
                    total: normalizedFiles.length,
                    existingDocument,
                })

                if (decision === 'skip') {
                    items.push({
                        fileName: file.name,
                        success: false,
                        skipped: true,
                        existingDocTitle: existingDocument.title,
                        error: `已放弃覆盖《${existingDocument.title || file.name}》`,
                    })
                    continue
                }

                options.onProgress?.({
                    total: normalizedFiles.length,
                    currentIndex: index + 1,
                    fileName: file.name,
                    stage: 'uploading',
                })
                imported = await importDocument(file, {
                    sourceUrl: options.sourceUrl,
                    docType: options.docType,
                    overwriteDocId: existingDocument.doc_id,
                })
            }
            options.onProgress?.({
                total: normalizedFiles.length,
                currentIndex: index + 1,
                fileName: file.name,
                stage: 'indexing',
            })
            const indexed = await indexDocument(imported.doc_id, options.chunkSize, options.overlap)
            items.push({
                fileName: file.name,
                success: true,
                doc_id: imported.doc_id,
                title: imported.title,
                doc_type: imported.doc_type,
                status: indexed.status,
                chunks: indexed.chunks,
                overwritten: imported.overwritten,
            })
        } catch (error: any) {
            items.push({
                fileName: file.name,
                success: false,
                error: error?.message || '未知错误',
            })
        }
    }

    const successCount = items.filter((item) => item.success).length
    const skippedCount = items.filter((item) => item.skipped).length
    const failureCount = items.filter((item) => !item.success && !item.skipped).length

    return {
        items,
        total: normalizedFiles.length,
        successCount,
        failureCount,
        skippedCount,
    }
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

export async function getDocumentDetail(docId: string): Promise<DocumentDetail> {
    const envelope = await apiClient.get<ApiEnvelope<DocumentDetail>>(`/api/v1/docs/${docId}/detail`)
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

            if (event === 'metadata') {
                handlers.onMetadata?.(JSON.parse(data))
            } else if (event === 'token') {
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

export async function getCitationOpenTarget(citationId: string): Promise<CitationOpenTarget> {
    const envelope = await apiClient.get<ApiEnvelope<CitationOpenTarget>>(`/api/v1/citations/${citationId}/open-target`)
    return unwrap(envelope)
}

export async function getDocumentViewerContent(docId: string, citationId: string): Promise<DocumentViewerContent> {
    const envelope = await apiClient.get<ApiEnvelope<DocumentViewerContent>>(`/api/v1/docs/${docId}/viewer-content`, {
        citation_id: citationId,
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

export async function createChatSession(title?: string): Promise<ChatSessionSummary> {
    const envelope = await apiClient.post<ApiEnvelope<ChatSessionSummary>>('/api/v1/chat/sessions', { title })
    return unwrap(envelope)
}

export async function listChatSessions(limit = 20, status: 'active' | 'archived' | 'all' = 'active'): Promise<{ items: ChatSessionSummary[] }> {
    const envelope = await apiClient.get<ApiEnvelope<{ items: ChatSessionSummary[] }>>('/api/v1/chat/sessions', { limit, status })
    return unwrap(envelope)
}

export async function getChatSessionDetail(sessionId: string, messageLimit = 50): Promise<ChatSessionDetail> {
    const envelope = await apiClient.get<ApiEnvelope<ChatSessionDetail>>(`/api/v1/chat/sessions/${sessionId}`, {
        message_limit: messageLimit,
    })
    return unwrap(envelope)
}

export async function getChatSessionMessages(
    sessionId: string,
    limit = 50,
    beforeSeq?: number
): Promise<{ session_id: string; messages: ChatHistoryMessage[] }> {
    const envelope = await apiClient.get<ApiEnvelope<{ session_id: string; messages: ChatHistoryMessage[] }>>(
        `/api/v1/chat/sessions/${sessionId}/messages`,
        { limit, before_seq: beforeSeq }
    )
    return unwrap(envelope)
}

export async function updateChatSession(
    sessionId: string,
    payload: { title?: string; status?: 'active' | 'archived' | 'deleted' }
): Promise<ChatSessionSummary> {
    const envelope = await apiClient.patch<ApiEnvelope<ChatSessionSummary>>(`/api/v1/chat/sessions/${sessionId}`, payload)
    return unwrap(envelope)
}

export async function deleteChatSession(sessionId: string): Promise<{ session_id: string; deleted: boolean }> {
    const envelope = await apiClient.delete<ApiEnvelope<{ session_id: string; deleted: boolean }>>(`/api/v1/chat/sessions/${sessionId}`)
    return unwrap(envelope)
}

export async function chatSessionMessage(
    sessionId: string,
    request: Omit<ChatCompletionRequest, 'session_id'>
): Promise<ChatCompletionData> {
    const envelope = await apiClient.post<ApiEnvelope<ChatCompletionData>>(
        `/api/v1/chat/sessions/${sessionId}/messages`,
        withDefaults({ ...request, session_id: sessionId })
    )
    return unwrap(envelope)
}

export async function chatSessionMessageStream(
    sessionId: string,
    request: Omit<ChatCompletionRequest, 'session_id'>,
    handlers: StreamHandlers = {}
): Promise<void> {
    const response = await fetch(`${apiClient['baseUrl']}/api/v1/chat/sessions/${sessionId}/messages:stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(withDefaults({ ...request, session_id: sessionId })),
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

            if (event === 'metadata') {
                handlers.onMetadata?.(JSON.parse(data))
            } else if (event === 'token') {
                try {
                    handlers.onToken?.(JSON.parse(data))
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

export async function listDocuments(): Promise<{ items: DocStatusResult[] }> {
    const envelope = await apiClient.get<ApiEnvelope<{ items: DocStatusResult[] }>>('/api/v1/docs')
    return unwrap(envelope)
}

export async function deleteDocument(docId: string): Promise<{ doc_id: string; deleted: boolean }> {
    const envelope = await apiClient.delete<ApiEnvelope<{ doc_id: string; deleted: boolean }>>(`/api/v1/docs/${docId}`)
    return unwrap(envelope)
}
