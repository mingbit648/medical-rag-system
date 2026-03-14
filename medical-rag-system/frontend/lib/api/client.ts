// API 客户端配置
// 生产环境使用相对路径，由 Nginx 代理转发
// 开发环境使用绝对地址直连后端

const API_BASE_URL =
    process.env.NEXT_PUBLIC_API_BASE_URL !== undefined
        ? process.env.NEXT_PUBLIC_API_BASE_URL
        : (process.env.NODE_ENV === 'development' ? 'http://localhost:8002' : '')

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
    ; (error as any).status = response.status
    if (detail && typeof detail === 'object' && typeof detail.code === 'string') {
        ; (error as any).code = detail.code
    }
    return error
}

export class ApiClient {
    private baseUrl: string

    constructor(baseUrl: string = API_BASE_URL) {
        this.baseUrl = baseUrl
    }

    private async request<T>(
        endpoint: string,
        options: RequestInit = {},
        signal?: AbortSignal
    ): Promise<T> {
        const url = `${this.baseUrl}${endpoint}`

        const headers: Record<string, string> = {
            'Content-Type': 'application/json',
            ...(options.headers as Record<string, string>),
        }

        const response = await fetch(url, {
            ...options,
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
                if (value !== undefined && value !== null) {
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
        return this.request<T>(endpoint, {
            method: 'POST',
            body: data ? JSON.stringify(data) : undefined,
        }, signal)
    }

    async put<T>(endpoint: string, data?: any): Promise<T> {
        return this.request<T>(endpoint, {
            method: 'PUT',
            body: data ? JSON.stringify(data) : undefined,
        })
    }

    async patch<T>(endpoint: string, data?: any): Promise<T> {
        return this.request<T>(endpoint, {
            method: 'PATCH',
            body: data ? JSON.stringify(data) : undefined,
        })
    }

    async delete<T>(endpoint: string): Promise<T> {
        return this.request<T>(endpoint, {
            method: 'DELETE',
        })
    }

    async stream(
        endpoint: string,
        data?: any,
        options: {
            onMessage?: (data: string) => void
            onError?: (error: Error) => void
            signal?: AbortSignal
        } = {}
    ): Promise<ReadableStream<Uint8Array>> {
        const url = `${this.baseUrl}${endpoint}`

        const headers: HeadersInit = {
            'Content-Type': 'application/json',
        }

        const response = await fetch(url, {
            method: 'POST',
            headers,
            body: data ? JSON.stringify(data) : undefined,
            signal: options.signal,
        })

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}))
            throw buildError(response, errorData)
        }

        if (!response.body) {
            throw new Error('响应体为空')
        }

        return response.body
    }
}

export const apiClient = new ApiClient()
