// API 客户端 — 法律辅助咨询 RAG 系统

// API 客户端配置
// 生产环境使用相对路径，由 Nginx 代理转发
// 开发环境使用绝对路径直连后端

const API_BASE_URL =
    process.env.NEXT_PUBLIC_API_BASE_URL !== undefined
        ? process.env.NEXT_PUBLIC_API_BASE_URL
        : (process.env.NODE_ENV === 'development' ? 'http://localhost:8002' : '')

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
            const error = new Error(errorData.detail || errorData.message || `请求失败: ${response.statusText}`)
                ; (error as any).status = response.status
            throw error
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

    async delete<T>(endpoint: string): Promise<T> {
        return this.request<T>(endpoint, {
            method: 'DELETE',
        })
    }

    /**
     * 流式请求（用于 SSE/流式响应）
     */
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
            const error = new Error(errorData.detail || errorData.message || `请求失败: ${response.statusText}`)
                ; (error as any).status = response.status
            throw error
        }

        if (!response.body) {
            throw new Error('响应体为空')
        }

        return response.body
    }
}

export const apiClient = new ApiClient()
