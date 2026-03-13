# AI 回复中的操作保护功能

## 功能说明

在 AI 回复流式输出过程中或等待 AI 回复时，系统会自动拦截以下操作，并显示友好提示："AI 正在回复中，请稍候..."

## 受保护的操作

### 1. 会话切换
- **位置**: 侧边栏会话列表
- **行为**: 点击其他会话时显示提示，阻止切换
- **适用场景**: 桌面端和移动端

### 2. 新建对话
- **位置**: 
  - 桌面端: "开启新对话" 按钮
  - 移动端: 顶部导航栏的新建按钮
- **行为**: 点击时显示提示，阻止新建

### 3. 归档当前会话
- **位置**: 会话右键菜单 → 归档
- **行为**: 仅当归档当前正在回复的会话时拦截
- **说明**: 归档其他会话不受影响

### 4. 删除当前会话
- **位置**: 会话右键菜单 → 删除
- **行为**: 仅当删除当前正在回复的会话时拦截
- **说明**: 删除其他会话不受影响

### 5. 归档管理弹窗中的会话切换
- **位置**: 设置菜单 → 管理归档 → 会话列表
- **行为**: 点击会话时显示提示，阻止切换

## 实现细节

### 技术方案
使用 React Context API 在组件间同步 AI 响应状态

### 文件修改清单

1. **lib/contexts/ChatLoadingContext.tsx** (新建)
   - 创建 `ChatLoadingContext` 和 `ChatLoadingProvider`
   - 导出 `useChatLoading` Hook

2. **app/chat/layout.tsx**
   - 保持简洁，只包含 `AuthGuard` 和 `ChatLayoutClient`
   - 移除 `ChatLoadingProvider`（移到 layout-client.tsx）

3. **app/chat/layout-client.tsx**
   - 导入 `useChatLoading` 和 `ChatLoadingProvider`
   - 在 `UserProvider` 内部包裹 `ChatLoadingProvider`
   - 在以下函数中添加拦截逻辑：
     - `handleConversationChange`
     - `handleCreateSession`
     - `handleArchiveConversation`
     - `handleDeleteConversation`
     - 归档管理弹窗的 `onActiveChange`

4. **app/chat/conversation/page.tsx**
   - 导入 `useChatLoading`
   - 同步 `isAIResponding` 状态
   - 组件卸载时清除状态

### 状态触发条件

```typescript
isAIResponding = requestLoading || submittingRef.current
```

- `requestLoading`: 正在接收流式响应
- `submittingRef.current`: 正在提交请求

## 用户体验

### 视觉效果
- ✅ 按钮和列表保持正常外观（无 disabled 样式）
- ✅ 点击时显示友好提示
- ✅ 不影响其他功能（设置、退出登录等）

### 提示文案
```
AI 正在回复中，请稍候...
```

## 测试场景

### 基础功能测试
1. ✅ 发送消息 → AI 回复 → 完成后可以切换会话
2. ✅ 发送消息 → 立即点击其他会话 → 显示提示
3. ✅ 发送消息 → 立即点击新建对话 → 显示提示
4. ✅ 发送消息 → 立即归档当前会话 → 显示提示
5. ✅ 发送消息 → 立即删除当前会话 → 显示提示

### 边界情况测试
1. ✅ 归档/删除其他会话 → 不受影响
2. ✅ 移动端抽屉中的操作 → 正确拦截
3. ✅ 归档管理弹窗中的操作 → 正确拦截
4. ✅ 页面刷新 → 状态正确重置
5. ✅ 请求失败 → 状态正确解锁
6. ✅ 组件卸载 → 状态正确清除

## 注意事项

1. **不影响其他会话**: 只有当前正在回复的会话受保护
2. **状态自动清除**: 组件卸载或请求完成后自动解锁
3. **页面刷新**: 状态会丢失（符合预期，因为流式连接已断开）
4. **多标签页**: 每个标签页独立状态，互不影响

## 技术细节

### Provider 层级结构

为了兼容 `output: 'export'` 静态导出模式，Provider 的嵌套结构如下：

```
AuthGuard (Server Component)
  └─ ChatLayoutClient ('use client')
      └─ UserProvider
          └─ ChatLoadingProvider  ← 在 Client Component 内部
              └─ ChatLayoutContent
                  └─ children
```

**重要**：`ChatLoadingProvider` 必须在 `ChatLayoutClient` 内部（Client Component 边界内），而不是在 `layout.tsx`（Server Component）中。这样可以避免静态导出时的 chunk 加载问题。
