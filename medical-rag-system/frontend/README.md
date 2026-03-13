# 辅助诊断系统 - 医生端

基于 Next.js 14 (App Router) 构建的 AI 辅助诊断医生 Web 端应用，参考 ChatGPT 界面设计。

## 技术栈

- Next.js 14 (App Router) + TypeScript
- Ant Design 5 + @ant-design/x
- Tailwind CSS
- Jest (单元测试)

## 快速开始

```bash
# 安装依赖
npm install

# 启动开发服务器
npm run dev

# 构建生产版本 (静态导出)
npm run build

# 启动生产服务器
npm start

# 代码检查
npm run lint

# 运行测试
npm test
```

开发服务器启动后访问 [http://localhost:3000](http://localhost:3000)

## 环境变量

创建 `.env.local` 或修改 `.env.development`：

```bash
NEXT_PUBLIC_API_BASE_URL=http://localhost:8002
```

## 项目结构

```
doctor-web/
├── app/
│   ├── layout.tsx           # 根布局
│   ├── page.tsx             # 首页
│   ├── login/               # 登录页
│   └── chat/                # 聊天模块
│       ├── layout.tsx       # 聊天布局
│       ├── page.tsx         # 聊天首页
│       └── conversation/    # 对话详情页
├── components/
│   ├── AuthGuard/           # 认证守卫
│   ├── CustomSpeechButton/  # 语音按钮
│   ├── MedicalGuides/       # 医疗指南
│   ├── MobileHeader/        # 移动端头部
│   ├── QuotaDisplay/        # 额度显示
│   ├── RemarkModal/         # 备注弹窗
│   ├── StatusBar/           # 状态栏
│   └── StatusSkeleton/      # 加载骨架屏
├── lib/
│   ├── api/                 # API 服务
│   │   ├── auth.ts          # 认证 API
│   │   ├── client.ts        # HTTP 客户端
│   │   ├── diagnosis.ts     # 诊断 API
│   │   └── types.ts         # 类型定义
│   ├── contexts/            # React Context
│   │   ├── ChatLoadingContext.tsx
│   │   └── UserContext.tsx
│   ├── hooks/               # 自定义 Hooks
│   │   ├── useCustomSpeech.ts
│   │   ├── useFileUpload.ts
│   │   ├── useMediaQuery.ts
│   │   └── usePreventRefresh.ts
│   ├── utils/               # 工具函数
│   │   ├── deviceDetector.ts
│   │   ├── errorHandler.ts
│   │   ├── exportUtils.ts
│   │   ├── fileValidation.ts
│   │   ├── markdown.ts
│   │   └── typewriter.ts
│   └── workflow/            # 工作流配置
└── scripts/
    └── build.js             # 构建脚本
```

## 功能特性

- 响应式设计，支持桌面端和移动端
- 类 ChatGPT 对话界面
- 会话管理（创建、查看、删除）
- AI 诊断对话
- Markdown 消息渲染
- 语音输入支持
- 医疗指南查看
- 对话导出功能
- 用户认证与 Token 管理

## API 集成

- 用户登录 `POST /api/v1/users/login`
- 会话列表 `GET /api/v1/diagnosis/sessions`
- 创建会话 `POST /api/v1/diagnosis/sessions`
- 会话详情 `GET /api/v1/diagnosis/sessions/{session_id}`
- 消息列表 `GET /api/v1/diagnosis/sessions/{session_id}/messages`
- AI 对话 `POST /api/v1/diagnosis/sessions/{session_id}/chat`

## 部署

项目配置为静态导出模式 (`output: 'export'`)，构建产物在 `out/` 目录，可直接部署到 Nginx 等静态服务器。

Docker 部署参考 `dockerfile` 和 `nginx.conf`。

