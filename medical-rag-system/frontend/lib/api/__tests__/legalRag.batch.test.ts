import { apiClient } from '@/lib/api/client'
import { importDocuments } from '@/lib/api/legalRag'

function makeImportEnvelope(docId: string, title: string, docType = 'pdf', overwritten = false) {
    return {
        code: 0,
        message: 'ok',
        data: {
            doc_id: docId,
            title,
            doc_type: docType,
            status: 'imported',
            overwritten,
        },
        trace_id: `trace_${docId}`,
    }
}

function makeDuplicateErrorEnvelope(docId: string, title: string) {
    return {
        detail: {
            code: 'DOCUMENT_ALREADY_EXISTS',
            message: `知识库已有《${title}》，请确认是否覆盖。`,
            existing_doc: {
                doc_id: docId,
                title,
                doc_type: 'pdf',
                parse_status: 'indexed',
                chunks: 6,
                created_at: '2026-03-19T10:00:00+08:00',
                original_file_name: `${title}.pdf`,
            },
        },
    }
}

function makeIndexEnvelope(docId: string, jobId: string, kbId = 'kb_default') {
    return {
        code: 0,
        message: 'ok',
        data: {
            job_id: jobId,
            doc_id: docId,
            kb_id: kbId,
            status: 'indexing',
            parse_status: 'indexing',
        },
        trace_id: `trace_index_${docId}`,
    }
}

describe('importDocuments', () => {
    const originalFetch = global.fetch

    afterEach(() => {
        jest.restoreAllMocks()
        global.fetch = originalFetch
    })

    test('imports files sequentially and queues indexing while reporting progress', async () => {
        const fetchMock = jest.fn()
        global.fetch = fetchMock as typeof fetch
        fetchMock
            .mockResolvedValueOnce({
                ok: true,
                json: async () => makeImportEnvelope('doc_alpha', 'alpha.pdf'),
            } as Response)
            .mockResolvedValueOnce({
                ok: true,
                json: async () => makeImportEnvelope('doc_beta', 'beta.txt', 'text'),
            } as Response)

        const postSpy = jest
            .spyOn(apiClient, 'post')
            .mockResolvedValueOnce(makeIndexEnvelope('doc_alpha', 'job_alpha'))
            .mockResolvedValueOnce(makeIndexEnvelope('doc_beta', 'job_beta'))

        const onProgress = jest.fn()
        const result = await importDocuments(
            [
                new File(['alpha'], 'alpha.pdf', { type: 'application/pdf' }),
                new File(['beta'], 'beta.txt', { type: 'text/plain' }),
            ],
            { onProgress }
        )

        expect(fetchMock).toHaveBeenCalledTimes(2)
        expect(postSpy).toHaveBeenCalledTimes(2)
        expect(postSpy).toHaveBeenNthCalledWith(
            1,
            '/api/v1/docs/doc_alpha/index',
            expect.objectContaining({
                chunk: { size: 800, overlap: 200 },
            })
        )
        expect(result).toEqual({
            items: [
                expect.objectContaining({
                    fileName: 'alpha.pdf',
                    success: true,
                    doc_id: 'doc_alpha',
                    status: 'indexing',
                    latestJob: {
                        job_id: 'job_alpha',
                        status: 'indexing',
                        attempts: 0,
                    },
                }),
                expect.objectContaining({
                    fileName: 'beta.txt',
                    success: true,
                    doc_id: 'doc_beta',
                    status: 'indexing',
                    latestJob: {
                        job_id: 'job_beta',
                        status: 'indexing',
                        attempts: 0,
                    },
                }),
            ],
            total: 2,
            successCount: 2,
            failureCount: 0,
            skippedCount: 0,
        })
        expect(onProgress.mock.calls).toEqual([
            [{ total: 2, currentIndex: 1, fileName: 'alpha.pdf', stage: 'uploading' }],
            [{ total: 2, currentIndex: 1, fileName: 'alpha.pdf', stage: 'indexing' }],
            [{ total: 2, currentIndex: 2, fileName: 'beta.txt', stage: 'uploading' }],
            [{ total: 2, currentIndex: 2, fileName: 'beta.txt', stage: 'indexing' }],
        ])
    })

    test('continues remaining files after queueing failure and records the error', async () => {
        const fetchMock = jest.fn()
        global.fetch = fetchMock as typeof fetch
        fetchMock
            .mockResolvedValueOnce({
                ok: true,
                json: async () => makeImportEnvelope('doc_alpha', 'alpha.pdf'),
            } as Response)
            .mockResolvedValueOnce({
                ok: true,
                json: async () => makeImportEnvelope('doc_beta', 'beta.pdf'),
            } as Response)

        jest.spyOn(apiClient, 'post')
            .mockRejectedValueOnce(new Error('索引失败'))
            .mockResolvedValueOnce(makeIndexEnvelope('doc_beta', 'job_beta'))

        const result = await importDocuments(
            [
                new File(['alpha'], 'alpha.pdf', { type: 'application/pdf' }),
                new File(['beta'], 'beta.pdf', { type: 'application/pdf' }),
            ]
        )

        expect(result.total).toBe(2)
        expect(result.successCount).toBe(1)
        expect(result.failureCount).toBe(1)
        expect(result.skippedCount).toBe(0)
        expect(result.items).toEqual([
            expect.objectContaining({
                fileName: 'alpha.pdf',
                success: false,
                error: '索引失败',
            }),
            expect.objectContaining({
                fileName: 'beta.pdf',
                success: true,
                doc_id: 'doc_beta',
                status: 'indexing',
                latestJob: {
                    job_id: 'job_beta',
                    status: 'indexing',
                    attempts: 0,
                },
            }),
        ])
    })

    test('skips duplicate documents when user declines overwrite', async () => {
        const fetchMock = jest.fn()
        global.fetch = fetchMock as typeof fetch
        fetchMock.mockResolvedValueOnce({
            ok: false,
            status: 409,
            json: async () => makeDuplicateErrorEnvelope('doc_existing', 'employee-handbook'),
        } as Response)

        const postSpy = jest.spyOn(apiClient, 'post')
        const onDuplicate = jest.fn().mockResolvedValue('skip')
        const onProgress = jest.fn()

        const result = await importDocuments(
            [new File(['duplicate'], 'employee-handbook.pdf', { type: 'application/pdf' })],
            { onDuplicate, onProgress }
        )

        expect(onDuplicate).toHaveBeenCalledWith(
            expect.objectContaining({
                currentIndex: 1,
                total: 1,
                existingDocument: expect.objectContaining({ doc_id: 'doc_existing', title: 'employee-handbook' }),
            })
        )
        expect(postSpy).not.toHaveBeenCalled()
        expect(result).toEqual({
            items: [
                expect.objectContaining({
                    fileName: 'employee-handbook.pdf',
                    success: false,
                    skipped: true,
                    existingDocTitle: 'employee-handbook',
                    error: '已放弃覆盖《employee-handbook》',
                }),
            ],
            total: 1,
            successCount: 0,
            failureCount: 0,
            skippedCount: 1,
        })
        expect(onProgress.mock.calls).toEqual([
            [{ total: 1, currentIndex: 1, fileName: 'employee-handbook.pdf', stage: 'uploading' }],
            [{ total: 1, currentIndex: 1, fileName: 'employee-handbook.pdf', stage: 'awaiting_confirmation' }],
        ])
    })

    test('retries duplicate documents with overwrite when user confirms', async () => {
        const fetchMock = jest.fn()
        global.fetch = fetchMock as typeof fetch
        fetchMock
            .mockResolvedValueOnce({
                ok: false,
                status: 409,
                json: async () => makeDuplicateErrorEnvelope('doc_existing', 'policy'),
            } as Response)
            .mockResolvedValueOnce({
                ok: true,
                json: async () => makeImportEnvelope('doc_existing', 'policy', 'pdf', true),
            } as Response)

        const postSpy = jest.spyOn(apiClient, 'post').mockResolvedValueOnce(makeIndexEnvelope('doc_existing', 'job_existing'))
        const onDuplicate = jest.fn().mockResolvedValue('overwrite')

        const result = await importDocuments([new File(['duplicate'], 'policy.pdf', { type: 'application/pdf' })], {
            onDuplicate,
        })

        expect(fetchMock).toHaveBeenCalledTimes(2)
        expect(postSpy).toHaveBeenCalledTimes(1)
        expect(result).toEqual({
            items: [
                expect.objectContaining({
                    fileName: 'policy.pdf',
                    success: true,
                    doc_id: 'doc_existing',
                    status: 'indexing',
                    overwritten: true,
                    latestJob: {
                        job_id: 'job_existing',
                        status: 'indexing',
                        attempts: 0,
                    },
                }),
            ],
            total: 1,
            successCount: 1,
            failureCount: 0,
            skippedCount: 0,
        })
    })
})
