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

function makeIndexEnvelope(docId: string, chunks: number) {
    return {
        code: 0,
        message: 'ok',
        data: {
            doc_id: docId,
            status: 'indexed',
            chunks,
            chunk: {
                size: 800,
                overlap: 200,
            },
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

    test('imports and indexes files sequentially while reporting progress', async () => {
        const fetchMock = jest.fn()
        global.fetch = fetchMock as typeof fetch
        fetchMock
            .mockResolvedValueOnce({
                ok: true,
                json: async () => makeImportEnvelope('doc_alpha', '劳动合同.pdf'),
            } as Response)
            .mockResolvedValueOnce({
                ok: true,
                json: async () => makeImportEnvelope('doc_beta', '规章制度.txt', 'text'),
            } as Response)

        const postSpy = jest
            .spyOn(apiClient, 'post')
            .mockResolvedValueOnce(makeIndexEnvelope('doc_alpha', 3))
            .mockResolvedValueOnce(makeIndexEnvelope('doc_beta', 5))

        const onProgress = jest.fn()
        const result = await importDocuments(
            [
                new File(['alpha'], '劳动合同.pdf', { type: 'application/pdf' }),
                new File(['beta'], '规章制度.txt', { type: 'text/plain' }),
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
                    fileName: '劳动合同.pdf',
                    success: true,
                    doc_id: 'doc_alpha',
                    chunks: 3,
                }),
                expect.objectContaining({
                    fileName: '规章制度.txt',
                    success: true,
                    doc_id: 'doc_beta',
                    chunks: 5,
                }),
            ],
            total: 2,
            successCount: 2,
            failureCount: 0,
            skippedCount: 0,
        })
        expect(onProgress.mock.calls).toEqual([
            [{ total: 2, currentIndex: 1, fileName: '劳动合同.pdf', stage: 'uploading' }],
            [{ total: 2, currentIndex: 1, fileName: '劳动合同.pdf', stage: 'indexing' }],
            [{ total: 2, currentIndex: 2, fileName: '规章制度.txt', stage: 'uploading' }],
            [{ total: 2, currentIndex: 2, fileName: '规章制度.txt', stage: 'indexing' }],
        ])
    })

    test('continues remaining files after a failure and records the error', async () => {
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
            .mockResolvedValueOnce(makeIndexEnvelope('doc_beta', 4))

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
                chunks: 4,
            }),
        ])
    })

    test('skips duplicate documents when user declines overwrite', async () => {
        const fetchMock = jest.fn()
        global.fetch = fetchMock as typeof fetch
        fetchMock.mockResolvedValueOnce({
            ok: false,
            status: 409,
            json: async () => makeDuplicateErrorEnvelope('doc_existing', '员工手册'),
        } as Response)

        const postSpy = jest.spyOn(apiClient, 'post')
        const onDuplicate = jest.fn().mockResolvedValue('skip')
        const onProgress = jest.fn()

        const result = await importDocuments(
            [new File(['duplicate'], '员工手册.pdf', { type: 'application/pdf' })],
            { onDuplicate, onProgress }
        )

        expect(onDuplicate).toHaveBeenCalledWith(
            expect.objectContaining({
                currentIndex: 1,
                total: 1,
                existingDocument: expect.objectContaining({ doc_id: 'doc_existing', title: '员工手册' }),
            })
        )
        expect(postSpy).not.toHaveBeenCalled()
        expect(result).toEqual({
            items: [
                expect.objectContaining({
                    fileName: '员工手册.pdf',
                    success: false,
                    skipped: true,
                    existingDocTitle: '员工手册',
                    error: '已放弃覆盖《员工手册》',
                }),
            ],
            total: 1,
            successCount: 0,
            failureCount: 0,
            skippedCount: 1,
        })
        expect(onProgress.mock.calls).toEqual([
            [{ total: 1, currentIndex: 1, fileName: '员工手册.pdf', stage: 'uploading' }],
            [{ total: 1, currentIndex: 1, fileName: '员工手册.pdf', stage: 'awaiting_confirmation' }],
        ])
    })

    test('retries duplicate documents with overwrite when user confirms', async () => {
        const fetchMock = jest.fn()
        global.fetch = fetchMock as typeof fetch
        fetchMock
            .mockResolvedValueOnce({
                ok: false,
                status: 409,
                json: async () => makeDuplicateErrorEnvelope('doc_existing', '规章制度'),
            } as Response)
            .mockResolvedValueOnce({
                ok: true,
                json: async () => makeImportEnvelope('doc_existing', '规章制度', 'pdf', true),
            } as Response)

        const postSpy = jest.spyOn(apiClient, 'post').mockResolvedValueOnce(makeIndexEnvelope('doc_existing', 8))
        const onDuplicate = jest.fn().mockResolvedValue('overwrite')

        const result = await importDocuments(
            [new File(['duplicate'], '规章制度.pdf', { type: 'application/pdf' })],
            { onDuplicate }
        )

        expect(fetchMock).toHaveBeenCalledTimes(2)
        expect(postSpy).toHaveBeenCalledTimes(1)
        expect(result).toEqual({
            items: [
                expect.objectContaining({
                    fileName: '规章制度.pdf',
                    success: true,
                    doc_id: 'doc_existing',
                    chunks: 8,
                    overwritten: true,
                }),
            ],
            total: 1,
            successCount: 1,
            failureCount: 0,
            skippedCount: 0,
        })
    })
})
