'use client'

import Link from 'next/link'
import { Alert, Button, Card, Form, Input, Typography } from 'antd'
import { useRouter } from 'next/navigation'
import { useEffect, useState } from 'react'
import { register } from '@/lib/api/legalRag'
import { useAppSession } from '@/lib/session/AppSessionProvider'


export default function RegisterPage() {
    const router = useRouter()
    const { loading, user, refreshSession } = useAppSession()
    const [submitting, setSubmitting] = useState(false)
    const [error, setError] = useState('')

    useEffect(() => {
        if (!loading && user) {
            router.replace('/chat')
        }
    }, [loading, router, user])

    async function handleFinish(values: { email: string; password: string; display_name?: string }) {
        setSubmitting(true)
        setError('')
        try {
            const result = await register(values)
            await refreshSession(result.default_kb_id || result.user.default_kb_id || undefined)
            router.replace('/chat')
        } catch (err: any) {
            setError(err?.message || '注册失败')
        } finally {
            setSubmitting(false)
        }
    }

    return (
        <main style={{ minHeight: '100vh', display: 'grid', placeItems: 'center', padding: 24, background: '#f7f7f5' }}>
            <Card style={{ width: '100%', maxWidth: 460 }}>
                <Typography.Title level={3} style={{ marginBottom: 8 }}>
                    注册
                </Typography.Title>
                <Typography.Paragraph type="secondary">
                    注册成功后会自动登录，并为你创建默认私有知识库。
                </Typography.Paragraph>
                {error ? <Alert type="error" showIcon message={error} style={{ marginBottom: 16 }} /> : null}
                <Form layout="vertical" onFinish={handleFinish}>
                    <Form.Item name="display_name" label="昵称">
                        <Input autoComplete="nickname" />
                    </Form.Item>
                    <Form.Item name="email" label="邮箱" rules={[{ required: true, message: '请输入邮箱' }]}>
                        <Input autoComplete="email" />
                    </Form.Item>
                    <Form.Item
                        name="password"
                        label="密码"
                        rules={[
                            { required: true, message: '请输入密码' },
                            { min: 8, message: '密码至少 8 位' },
                        ]}
                    >
                        <Input.Password autoComplete="new-password" />
                    </Form.Item>
                    <Button type="primary" htmlType="submit" loading={submitting} block>
                        注册并进入系统
                    </Button>
                </Form>
                <div style={{ marginTop: 16 }}>
                    <Link href="/login">已有账号？去登录</Link>
                </div>
            </Card>
        </main>
    )
}
