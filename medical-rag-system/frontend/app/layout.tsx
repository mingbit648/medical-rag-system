import type { Metadata, Viewport } from 'next'
import { AntdRegistry } from '@ant-design/nextjs-registry'
import './globals.css'
import AntdConfig from './antd-config'
import { AppSessionProvider } from '@/lib/session/AppSessionProvider'

export const metadata: Metadata = {
    title: '法律辅助咨询 RAG 系统 - 基于混合检索的智能法律信息检索',
    description: '基于混合检索策略（BM25+向量）+ 重排序的法律辅助咨询系统，面向劳动争议垂直领域，提供可追溯引用的智能问答。仅供学习与辅助检索，不构成法律意见。',
    keywords: ['法律咨询', 'RAG', '混合检索', '劳动争议', '法条检索', '引用溯源', '智能问答', 'BM25', '向量检索', '重排序'],
    metadataBase: new URL(process.env.NEXT_PUBLIC_SITE_URL || 'http://localhost:3000'),
    icons: {
        icon: [
            { url: '/icon.svg', type: 'image/svg+xml' },
            { url: '/favicon.ico', sizes: 'any' },
        ],
        apple: '/apple-touch-icon.png',
    },
    openGraph: {
        title: '法律辅助咨询 RAG 系统',
        description: '基于混合检索策略的法律辅助咨询系统，提供可追溯引用的智能问答',
        type: 'website',
    },
}

export const viewport: Viewport = {
    width: 'device-width',
    initialScale: 1,
    maximumScale: 1,
    userScalable: false,
}

export default function RootLayout({
    children,
}: {
    children: React.ReactNode
}) {
    return (
        <html lang="zh-CN" suppressHydrationWarning>
            <body className="antialiased" suppressHydrationWarning>
                <AntdRegistry>
                    <AntdConfig>
                        <AppSessionProvider>{children}</AppSessionProvider>
                    </AntdConfig>
                </AntdRegistry>
            </body>
        </html>
    )
}
