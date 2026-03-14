'use client'

import { useEffect, useRef, useState, type MutableRefObject } from 'react'
import Link from 'next/link'
import { ArrowLeftOutlined, DownloadOutlined, FileTextOutlined } from '@ant-design/icons'
import { Empty, Spin, message } from 'antd'
import { resolveApiUrl } from '@/lib/api/client'
import { getDocumentViewerContent, type DocumentViewerContent } from '@/lib/api/legalRag'
import styles from './page.module.css'

interface ViewerParams {
    docId: string
    citationId: string
}

function readViewerParams(): ViewerParams | null {
    if (typeof window === 'undefined') return null
    const searchParams = new URLSearchParams(window.location.search)
    const docId = searchParams.get('doc_id') || ''
    const citationId = searchParams.get('citation_id') || ''
    if (!docId || !citationId) return null
    return { docId, citationId }
}

function renderViewerText(
    content: DocumentViewerContent,
    highlightRef: MutableRefObject<HTMLElement | null>
) {
    const text = content.text || ''
    const start = Math.max(0, Math.min(content.highlight.start, text.length))
    const end = Math.max(start, Math.min(content.highlight.end, text.length))

    if (start >= end) {
        return <div className={styles.text}>{text}</div>
    }

    return (
        <div className={styles.text}>
            {text.slice(0, start)}
            <mark ref={highlightRef} className={styles.highlight}>
                {text.slice(start, end)}
            </mark>
            {text.slice(end)}
        </div>
    )
}

export default function DocumentViewerPage() {
    const [params, setParams] = useState<ViewerParams | null>(null)
    const [content, setContent] = useState<DocumentViewerContent | null>(null)
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState('')
    const highlightRef = useRef<HTMLElement>(null)

    useEffect(() => {
        const nextParams = readViewerParams()
        setParams(nextParams)
        if (!nextParams) {
            setError('缺少文档定位参数')
            setLoading(false)
        }
    }, [])

    useEffect(() => {
        if (!params) return
        const currentParams = params
        let cancelled = false

        async function load() {
            setLoading(true)
            setError('')
            try {
                const nextContent = await getDocumentViewerContent(
                    currentParams.docId,
                    currentParams.citationId
                )
                if (!cancelled) setContent(nextContent)
            } catch (err: any) {
                if (cancelled) return
                const nextError = err?.message || '文档视图加载失败'
                setError(nextError)
                message.error(nextError)
            } finally {
                if (!cancelled) setLoading(false)
            }
        }

        void load()
        return () => {
            cancelled = true
        }
    }, [params])

    useEffect(() => {
        if (!content || !highlightRef.current) return
        const timer = window.setTimeout(() => {
            highlightRef.current?.scrollIntoView({ behavior: 'auto', block: 'center' })
        }, 0)
        return () => window.clearTimeout(timer)
    }, [content])

    const segmentLabel = content
        ? [content.citation_meta.section, content.citation_meta.article_no].filter(Boolean).join(' · ')
        : ''

    return (
        <div className={styles.page}>
            <div className={styles.shell}>
                <header className={styles.header}>
                    <div className={styles.intro}>
                        <span className={styles.kicker}>DOCUMENT VIEW</span>
                        <h1 className={styles.title}>{content?.title || '原文查看'}</h1>
                        <p className={styles.copy}>
                            {content
                                ? '直接展示原文并定位引用命中位置，不再按分块拆开展示。'
                                : '正在准备可定位的原文视图。'}
                        </p>
                    </div>

                    <div className={styles.toolbar}>
                        {content?.download_url ? (
                            <a
                                className={styles.toolbarLink}
                                href={resolveApiUrl(content.download_url)}
                                target="_blank"
                                rel="noreferrer"
                            >
                                <DownloadOutlined />
                                下载原件
                            </a>
                        ) : null}
                        <Link href="/chat" className={`${styles.toolbarLink} ${styles.toolbarLinkSubtle}`}>
                            <ArrowLeftOutlined />
                            返回聊天页
                        </Link>
                    </div>
                </header>

                <section className={styles.meta}>
                    <div className={styles.metaCard}>
                        <span className={styles.metaLabel}>文档类型</span>
                        <strong>{content?.doc_type?.toUpperCase() || '-'}</strong>
                    </div>
                    <div className={styles.metaCard}>
                        <span className={styles.metaLabel}>定位标签</span>
                        <strong>{segmentLabel || '命中片段'}</strong>
                    </div>
                    <div className={`${styles.metaCard} ${styles.metaCardWide}`}>
                        <span className={styles.metaLabel}>引用摘要</span>
                        <strong>{content?.citation_meta.snippet || '等待加载引用摘要'}</strong>
                    </div>
                </section>

                <main className={styles.main}>
                    {loading ? (
                        <div className={styles.loading}>
                            <Spin size="large" />
                        </div>
                    ) : error ? (
                        <div className={styles.empty}>
                            <Empty description={error} image={Empty.PRESENTED_IMAGE_SIMPLE} />
                        </div>
                    ) : content ? (
                        <section className={styles.paper}>
                            <div className={styles.paperHead}>
                                <div className={styles.paperTitle}>
                                    <FileTextOutlined />
                                    <span>原文视图</span>
                                </div>
                                <div className={styles.paperNote}>
                                    页面会直接定位到引用命中内容，正文保持连续阅读。
                                </div>
                            </div>

                            <div className={styles.paperBody}>
                                {renderViewerText(content, highlightRef)}
                            </div>
                        </section>
                    ) : (
                        <div className={styles.empty}>
                            <Empty description="暂无可展示的文档内容" image={Empty.PRESENTED_IMAGE_SIMPLE} />
                        </div>
                    )}
                </main>
            </div>
        </div>
    )
}
