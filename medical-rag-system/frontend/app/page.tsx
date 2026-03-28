'use client'

import { Spin } from 'antd'
import { useRouter } from 'next/navigation'
import { useEffect } from 'react'
import { useAppSession } from '@/lib/session/AppSessionProvider'


export default function HomePage() {
    const router = useRouter()
    const { loading, user } = useAppSession()

    useEffect(() => {
        if (loading) return
        router.replace(user ? '/chat' : '/login')
    }, [loading, router, user])

    return (
        <main style={{ minHeight: '100vh', display: 'grid', placeItems: 'center' }}>
            <Spin size="large" />
        </main>
    )
}
