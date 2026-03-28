'use client'

import Link from 'next/link'
import { Alert, Button, Card, Form, Input, Typography } from 'antd'
import { useRouter, useSearchParams } from 'next/navigation'
import { useEffect, useState } from 'react'
import { login } from '@/lib/api/legalRag'
import { useAppSession } from '@/lib/session/AppSessionProvider'


export default function LoginPage() {
    const router = useRouter()
    const searchParams = useSearchParams()
    const next = searchParams.get('next') || '/chat'
    const { loading, user, refreshSession } = useAppSession()
    const [submitting, setSubmitting] = useState(false)
    const [error, setError] = useState('')

    useEffect(() => {
        if (!loading && user) {
            router.replace(next)
        }
    }, [loading, next, router, user])

    async function handleFinish(values: { email: string; password: string }) {
        setSubmitting(true)
        setError('')
        try {
            const result = await login(values)
            await refreshSession(result.default_kb_id || result.user.default_kb_id || undefined)
            router.replace(next)
        } catch (err: any) {
            setError(err?.message || '登录失败')
        } finally {
            setSubmitting(false)
        }
    }

    return (
        <main style={{ minHeight: '100vh', display: 'grid', placeItems: 'center', padding: 24, background: '#f7f7f5' }}>
            <Card style={{ width: '100%', maxWidth: 420 }}>
                <Typography.Title level={3} style={{ marginBottom: 8 }}>
                    登录
                </Typography.Title>
                <Typography.Paragraph type="secondary">
                    登录后才能访问聊天工作台和知识库管理。
                </Typography.Paragraph>
                {error ? <Alert type="error" showIcon message={error} style={{ marginBottom: 16 }} /> : null}
                <Form layout="vertical" onFinish={handleFinish}>
                    <Form.Item name="email" label="邮箱" rules={[{ required: true, message: '请输入邮箱' }]}>
                        <Input autoComplete="email" />
                    </Form.Item>
                    <Form.Item name="password" label="密码" rules={[{ required: true, message: '请输入密码' }]}>
                        <Input.Password autoComplete="current-password" />
                    </Form.Item>
                    <Button type="primary" htmlType="submit" loading={submitting} block>
                        登录
                    </Button>
                </Form>
                <div style={{ marginTop: 16 }}>
                    <Link href="/register">没有账号？去注册</Link>
                </div>
            </Card>
        </main>
    )
}
