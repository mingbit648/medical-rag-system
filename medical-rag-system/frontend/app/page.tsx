'use client'

import Link from 'next/link'
import { useEffect } from 'react'

export default function Home() {
    useEffect(() => {
        const timer = window.setTimeout(() => {
            window.location.replace('/chat/')
        }, 180)

        return () => window.clearTimeout(timer)
    }, [])

    return (
        <main className="home-redirect">
            <div className="home-redirect-card">
                <div className="home-redirect-kicker">Redirecting To Workspace</div>
                <h1 className="home-redirect-title">正在进入法律辅助咨询工作台</h1>
                <p className="home-redirect-copy">
                    系统会自动跳转到对话页。如果浏览器没有及时跳转，可以直接打开工作台入口。
                </p>
                <div style={{ display: 'flex', gap: 16, marginTop: 18, flexWrap: 'wrap' }}>
                    <Link href="/chat/" className="home-redirect-link">
                        进入对话页
                    </Link>
                    <Link href="/knowledge/" className="home-redirect-link" style={{ color: 'var(--accent-navy)' }}>
                        知识库管理
                    </Link>
                </div>
            </div>
        </main>
    )
}
