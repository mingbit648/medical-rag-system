import markdownit from 'markdown-it';

const md = markdownit({
    html: true,      // 允许 HTML 标签
    breaks: true,    // 将换行符转换为 <br>
    linkify: true,   // 自动识别链接
});

export const renderMarkdown = (content: string): string => {
    return md.render(content);
};
