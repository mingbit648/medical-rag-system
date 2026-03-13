/** @type {import('next').NextConfig} */
const nextConfig = {
    output: 'export',
    trailingSlash: true,
    reactStrictMode: false,
    transpilePackages: ['@ant-design/x'],
    images: {
        unoptimized: true,
    },
    compiler: {
        removeConsole: process.env.NODE_ENV === 'production',
    },
    webpack: (config, { isServer }) => {
        if (!isServer) {
            config.resolve.fallback = {
                ...config.resolve.fallback,
                fs: false,
            }
        }
        return config
    },
}

module.exports = nextConfig
