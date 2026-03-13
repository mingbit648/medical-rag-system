import { useEffect, useState } from 'react';

/**
 * 响应式媒体查询 Hook
 * @param query - 媒体查询字符串，例如 '(max-width: 768px)'
 * @returns 是否匹配查询条件
 */
export function useMediaQuery(query: string): boolean {
    const [matches, setMatches] = useState(false);

    useEffect(() => {
        // 仅在客户端执行
        if (typeof window === 'undefined') {
            return;
        }

        const media = window.matchMedia(query);
        
        // 初始化状态
        setMatches(media.matches);

        // 监听变化
        const listener = (e: MediaQueryListEvent) => {
            setMatches(e.matches);
        };

        // 兼容旧版浏览器
        if (media.addEventListener) {
            media.addEventListener('change', listener);
        } else {
            // @ts-ignore - 兼容旧版 API
            media.addListener(listener);
        }

        return () => {
            if (media.removeEventListener) {
                media.removeEventListener('change', listener);
            } else {
                // @ts-ignore - 兼容旧版 API
                media.removeListener(listener);
            }
        };
    }, [query]);

    return matches;
}

/**
 * 检测是否为移动端设备
 * @returns 是否为移动端 (屏幕宽度 <= 768px)
 */
export function useIsMobile(): boolean {
    return useMediaQuery('(max-width: 768px)');
}

/**
 * 检测是否为平板设备
 * @returns 是否为平板 (屏幕宽度 769px - 1024px)
 */
export function useIsTablet(): boolean {
    return useMediaQuery('(min-width: 769px) and (max-width: 1024px)');
}
