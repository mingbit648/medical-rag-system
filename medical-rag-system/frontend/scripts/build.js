#!/usr/bin/env node

const { spawn } = require('child_process');
const path = require('path');

// 捕获未处理的 Promise 拒绝
const originalUnhandledRejection = process.listeners('unhandledRejection');
process.removeAllListeners('unhandledRejection');

process.on('unhandledRejection', (error) => {
  // 忽略 _document 页面不存在的错误（App Router 不需要此文件）
  if (error && error.type === 'PageNotFoundError' && error.code === 'ENOENT') {
    const errorMessage = error.message || error.stack || '';
    if (errorMessage.includes('_document') || errorMessage.includes('Cannot find module for page: /_document')) {
      // 静默忽略此错误，因为 App Router 不需要 _document
      return;
    }
  }
  // 其他错误正常处理
  if (originalUnhandledRejection.length > 0) {
    originalUnhandledRejection.forEach(listener => listener(error));
  } else {
    console.error('未处理的 Promise 拒绝:', error);
    process.exit(1);
  }
});

// 运行 Next.js 构建命令
const buildProcess = spawn('next', ['build'], {
  stdio: 'inherit',
  shell: true,
  cwd: path.resolve(__dirname, '..'),
  env: {
    ...process.env,
    // 设置环境变量来抑制某些警告
    NODE_ENV: 'production',
  },
});

buildProcess.on('close', (code) => {
  // 即使有 _document 错误，如果构建成功完成（code === 0），也认为成功
  if (code === 0) {
    console.log('\n✅ 构建成功完成');
    process.exit(0);
  } else {
    console.error(`\n❌ 构建失败，退出码: ${code}`);
    process.exit(code);
  }
});

buildProcess.on('error', (error) => {
  console.error('构建过程出错:', error);
  process.exit(1);
});

