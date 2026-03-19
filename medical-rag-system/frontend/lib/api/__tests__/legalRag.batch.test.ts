import { apiClient } from '@/lib/api/client'
import { importDocuments } from '@/lib/api/legalRag'

function makeImportEnvelope(docId: string, title: string, docType = 'pdf') {
    return {
        code: 0,
        message: 'ok',
        data: {
            doc_id: docId,
            title,
            doc_type: docType,
            status: 'imported',
        },
        trace_id: `trace_${docId}`,
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
})
