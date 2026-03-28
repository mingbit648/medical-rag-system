'use client'

import { Spin } from 'antd'
import { usePathname, useRouter } from 'next/navigation'
import { useEffect, type ReactNode } from 'react'
import { useAppSession } from '@/lib/session/AppSessionProvider'


export default function AuthGuard({ children }: { children: ReactNode }) {
    const router = useRouter()
    const pathname = usePathname()
    const { loading, user } = useAppSession()

    useEffect(() => {
        if (!loading && !user) {
            router.replace(`/login?next=${encodeURIComponent(pathname || '/chat')}`)
        }
    }, [loading, pathname, router, user])

    if (loading || !user) {
        return (
            <div style={{ minHeight: '100vh', display: 'grid', placeItems: 'center' }}>
                <Spin size="large" />
            </div>
        )
    }

    return <>{children}</>
}
