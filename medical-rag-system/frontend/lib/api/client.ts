const API_BASE_URL =
    process.env.NEXT_PUBLIC_API_BASE_URL !== undefined
        ? process.env.NEXT_PUBLIC_API_BASE_URL
        : process.env.NODE_ENV === 'development'
            ? 'http://localhost:8001'
            : ''

export function resolveApiUrl(endpoint: string): string {
    if (!endpoint) return endpoint
    if (/^https?:\/\//.test(endpoint)) return endpoint
    if (!endpoint.startsWith('/')) return endpoint
    return `${API_BASE_URL}${endpoint}`
}

function buildError(response: Response, errorData: any): Error {
    const detail = errorData?.detail
    const message =
        typeof detail === 'string'
            ? detail
            : detail?.message || errorData?.message || `请求失败: ${response.statusText}`
    const error = new Error(message)
    ;(error as any).status = response.status
    if (detail && typeof detail === 'object' && typeof detail.code === 'string') {
        ;(error as any).code = detail.code
    }
    if (detail && typeof detail === 'object' && detail.existing_doc) {
        ;(error as any).existingDocument = detail.existing_doc
    }
    return error
}

export class ApiClient {
    private baseUrl: string

    constructor(baseUrl: string = API_BASE_URL) {
        this.baseUrl = baseUrl
    }

    getBaseUrl(): string {
        return this.baseUrl
    }

    private async request<T>(
        endpoint: string,
        options: RequestInit = {},
        signal?: AbortSignal
    ): Promise<T> {
        const headers: Record<string, string> = {
            ...(options.headers as Record<string, string>),
        }

        if (!(options.body instanceof FormData) && !headers['Content-Type']) {
            headers['Content-Type'] = 'application/json'
        }

        const response = await fetch(`${this.baseUrl}${endpoint}`, {
            ...options,
            credentials: 'include',
            headers,
            signal,
        })

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}))
            throw buildError(response, errorData)
        }

        if (response.status === 204) {
            return {} as T
        }

        return response.json()
    }

    async get<T>(endpoint: string, params?: Record<string, any>, signal?: AbortSignal): Promise<T> {
        let fullUrl = endpoint
        if (params) {
            const searchParams = new URLSearchParams()
            Object.entries(params).forEach(([key, value]) => {
                if (value !== undefined && value !== null && value !== '') {
                    searchParams.append(key, String(value))
                }
            })
            const queryString = searchParams.toString()
            if (queryString) {
                fullUrl = `${endpoint}${endpoint.includes('?') ? '&' : '?'}${queryString}`
            }
        }
        return this.request<T>(fullUrl, {}, signal)
    }

    async post<T>(endpoint: string, data?: any, signal?: AbortSignal): Promise<T> {
        return this.request<T>(
            endpoint,
            {
                method: 'POST',
                body: data === undefined ? undefined : JSON.stringify(data),
            },
            signal
        )
    }

    async postForm<T>(endpoint: string, formData: FormData, signal?: AbortSignal): Promise<T> {
        return this.request<T>(
            endpoint,
            {
                method: 'POST',
                body: formData,
            },
            signal
        )
    }

    async patch<T>(endpoint: string, data?: any): Promise<T> {
        return this.request<T>(endpoint, {
            method: 'PATCH',
            body: data === undefined ? undefined : JSON.stringify(data),
        })
    }

    async delete<T>(endpoint: string): Promise<T> {
        return this.request<T>(endpoint, { method: 'DELETE' })
    }
}

export const apiClient = new ApiClient()
