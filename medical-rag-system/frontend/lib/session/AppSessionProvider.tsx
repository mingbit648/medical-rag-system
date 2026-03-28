'use client'

import {
    createContext,
    useCallback,
    useContext,
    useEffect,
    useMemo,
    useState,
    type ReactNode,
} from 'react'
import {
    getCurrentUser,
    listKnowledgeBases,
    logout as logoutRequest,
    type AuthUser,
    type KnowledgeBaseSummary,
} from '@/lib/api/legalRag'


const STORAGE_PREFIX = 'legal-rag'
const CURRENT_KB_KEY = 'current-kb'


export function buildScopedStorageKey(userId: string, key: string): string {
    return `${STORAGE_PREFIX}:${userId}:${key}`
}


export function clearScopedStorage(userId: string): void {
    if (typeof window === 'undefined') return
    const prefix = `${STORAGE_PREFIX}:${userId}:`
    Object.keys(window.localStorage).forEach((key) => {
        if (key.startsWith(prefix)) {
            window.localStorage.removeItem(key)
        }
    })
}


function resolveInitialKnowledgeBase(
    userId: string,
    items: KnowledgeBaseSummary[],
    defaultKbId?: string | null,
    preferredKbId?: string | null
): string | null {
    if (items.length === 0) return null
    const key = buildScopedStorageKey(userId, CURRENT_KB_KEY)
    const storedKbId =
        preferredKbId ||
        (typeof window !== 'undefined' ? window.localStorage.getItem(key) : null) ||
        defaultKbId ||
        items[0]?.kb_id
    return items.some((item) => item.kb_id === storedKbId) ? storedKbId : items[0]?.kb_id || null
}


interface AppSessionContextValue {
    loading: boolean
    user: AuthUser | null
    knowledgeBases: KnowledgeBaseSummary[]
    currentKnowledgeBase: KnowledgeBaseSummary | null
    currentKnowledgeBaseId: string | null
    refreshSession: (preferredKbId?: string | null) => Promise<void>
    refreshKnowledgeBases: (preferredKbId?: string | null) => Promise<void>
    selectKnowledgeBase: (kbId: string) => void
    logout: () => Promise<void>
}


const AppSessionContext = createContext<AppSessionContextValue | null>(null)


export function AppSessionProvider({ children }: { children: ReactNode }) {
    const [loading, setLoading] = useState(true)
    const [user, setUser] = useState<AuthUser | null>(null)
    const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBaseSummary[]>([])
    const [currentKnowledgeBaseId, setCurrentKnowledgeBaseId] = useState<string | null>(null)

    const selectKnowledgeBase = useCallback(
        (kbId: string) => {
            setCurrentKnowledgeBaseId(kbId)
            if (typeof window !== 'undefined' && user?.user_id) {
                window.localStorage.setItem(buildScopedStorageKey(user.user_id, CURRENT_KB_KEY), kbId)
            }
        },
        [user?.user_id]
    )

    const refreshKnowledgeBases = useCallback(
        async (preferredKbId?: string | null) => {
            if (!user?.user_id) {
                setKnowledgeBases([])
                setCurrentKnowledgeBaseId(null)
                return
            }

            const kbResult = await listKnowledgeBases()
            const items = kbResult.items || []
            setKnowledgeBases(items)

            const resolvedKbId = resolveInitialKnowledgeBase(
                user.user_id,
                items,
                user.default_kb_id,
                preferredKbId || currentKnowledgeBaseId
            )
            setCurrentKnowledgeBaseId(resolvedKbId)
            if (typeof window !== 'undefined' && resolvedKbId) {
                window.localStorage.setItem(buildScopedStorageKey(user.user_id, CURRENT_KB_KEY), resolvedKbId)
            }
        },
        [currentKnowledgeBaseId, user]
    )

    const refreshSession = useCallback(
        async (preferredKbId?: string | null) => {
            setLoading(true)
            try {
                const auth = await getCurrentUser()
                setUser(auth.user)
                const kbResult = await listKnowledgeBases()
                const items = kbResult.items || []
                setKnowledgeBases(items)
                const resolvedKbId = resolveInitialKnowledgeBase(
                    auth.user.user_id,
                    items,
                    auth.default_kb_id || auth.user.default_kb_id,
                    preferredKbId
                )
                setCurrentKnowledgeBaseId(resolvedKbId)
                if (typeof window !== 'undefined' && resolvedKbId) {
                    window.localStorage.setItem(buildScopedStorageKey(auth.user.user_id, CURRENT_KB_KEY), resolvedKbId)
                }
            } catch (error: any) {
                if (error?.status === 401) {
                    setUser(null)
                    setKnowledgeBases([])
                    setCurrentKnowledgeBaseId(null)
                    return
                }
                throw error
            } finally {
                setLoading(false)
            }
        },
        []
    )

    const logout = useCallback(async () => {
        const currentUserId = user?.user_id
        try {
            await logoutRequest()
        } finally {
            if (currentUserId) {
                clearScopedStorage(currentUserId)
            }
            setUser(null)
            setKnowledgeBases([])
            setCurrentKnowledgeBaseId(null)
        }
    }, [user?.user_id])

    useEffect(() => {
        void refreshSession()
    }, [refreshSession])

    const currentKnowledgeBase = useMemo(
        () => knowledgeBases.find((item) => item.kb_id === currentKnowledgeBaseId) || null,
        [currentKnowledgeBaseId, knowledgeBases]
    )

    const value = useMemo<AppSessionContextValue>(
        () => ({
            loading,
            user,
            knowledgeBases,
            currentKnowledgeBase,
            currentKnowledgeBaseId,
            refreshSession,
            refreshKnowledgeBases,
            selectKnowledgeBase,
            logout,
        }),
        [
            currentKnowledgeBase,
            currentKnowledgeBaseId,
            knowledgeBases,
            loading,
            logout,
            refreshKnowledgeBases,
            refreshSession,
            selectKnowledgeBase,
            user,
        ]
    )

    return <AppSessionContext.Provider value={value}>{children}</AppSessionContext.Provider>
}


export function useAppSession(): AppSessionContextValue {
    const context = useContext(AppSessionContext)
    if (!context) {
        throw new Error('useAppSession must be used within AppSessionProvider')
    }
    return context
}
