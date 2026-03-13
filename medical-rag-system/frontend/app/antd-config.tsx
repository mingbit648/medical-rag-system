'use client'

import { ConfigProvider } from 'antd'
import { StyleProvider } from 'antd-style'
import zhCN from 'antd/locale/zh_CN'
import { ReactNode } from 'react'
import 'antd/dist/reset.css'

export default function AntdConfig({ children }: { children: ReactNode }) {
  return (
    <StyleProvider>
      <ConfigProvider
        locale={zhCN}
        theme={{
          token: {
            colorPrimary: '#9f3d2f',
            colorInfo: '#9f3d2f',
            colorSuccess: '#2f6a48',
            colorWarning: '#b28743',
            colorError: '#8c2f26',
            colorTextBase: '#161617',
            colorText: '#2e3138',
            colorTextSecondary: '#70675d',
            colorBgBase: '#f7f0e5',
            colorBgContainer: 'rgba(255, 250, 242, 0.88)',
            colorBorder: 'rgba(42, 34, 28, 0.12)',
            colorSplit: 'rgba(42, 34, 28, 0.08)',
            borderRadius: 18,
            borderRadiusLG: 22,
            boxShadowSecondary: '0 16px 40px rgba(33, 24, 19, 0.08)',
            fontFamily: '"PingFang SC", "Hiragino Sans GB", "Microsoft YaHei UI", sans-serif',
          },
          components: {
            Button: {
              borderRadius: 999,
              controlHeight: 40,
              paddingInline: 16,
              defaultShadow: 'none',
              primaryShadow: '0 12px 24px rgba(111, 36, 27, 0.18)',
            },
            Input: {
              borderRadius: 18,
              activeBorderColor: '#9f3d2f',
              hoverBorderColor: '#9f3d2f',
            },
            Drawer: {
              colorBgElevated: '#fffaf2',
            },
            Tag: {
              borderRadiusSM: 999,
              defaultBg: 'rgba(22, 50, 77, 0.06)',
              defaultColor: '#16324d',
            },
            Collapse: {
              headerBg: 'transparent',
              contentBg: 'transparent',
            },
          },
        }}
      >
        {children}
      </ConfigProvider>
    </StyleProvider>
  )
}
