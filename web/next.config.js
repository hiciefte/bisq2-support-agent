/** @type {import('next').NextConfig} */
const nextConfig = {
    typescript: {
        // !! WARN !!
        // Dangerously allow production builds to successfully complete even if
        // your project has type errors.
        // !! WARN !!
        ignoreBuildErrors: true,
    },
    eslint: {
        // Warning: This allows production builds to successfully complete even if
        // your project has ESLint errors.
        ignoreDuringBuilds: true,
    },
    // Disable automatic HTTPS
    experimental: {
        forceSwcTransforms: true,
    },
    // Security: Remove fingerprinting
    poweredByHeader: false,
    generateBuildId: async () => {
        // Use dynamic build ID based on git commit hash for cache invalidation
        // BUILD_ID is injected via Docker build arg: --build-arg BUILD_ID=build-{hash}
        // Format: build-{git-hash} (e.g., build-a3f2c1b)
        // Fallback to constant for backward compatibility if not provided
        const buildId = process.env.NEXT_BUILD_ID || 'bisq-support-build';
        return buildId;
    },
    // Performance optimizations
    compress: true,
    reactStrictMode: true,

    // Image optimization
    images: {
        formats: ['image/avif', 'image/webp'],
        deviceSizes: [640, 750, 828, 1080, 1200, 1920],
        imageSizes: [16, 32, 48, 64, 96, 128, 256],
    },

    // Security headers (applies in dev and standalone mode; nginx handles in production)
    async headers() {
        return [
            {
                source: '/:path*',
                headers: [
                    {
                        key: 'X-DNS-Prefetch-Control',
                        value: 'on',
                    },
                    {
                        key: 'X-Content-Type-Options',
                        value: 'nosniff',
                    },
                    {
                        key: 'Referrer-Policy',
                        value: 'strict-origin-when-cross-origin',
                    },
                    {
                        key: 'X-Frame-Options',
                        value: 'SAMEORIGIN',
                    },
                    {
                        key: 'Permissions-Policy',
                        value: 'camera=(), microphone=(), geolocation=()',
                    },
                ],
            },
        ];
    },
};

// Conditionally wrap with bundle analyzer (only available when ANALYZE=true and dev deps installed)
let exportedConfig = nextConfig;
if (process.env.ANALYZE === 'true') {
    try {
        const withBundleAnalyzer = require('@next/bundle-analyzer')({
            enabled: true,
        });
        exportedConfig = withBundleAnalyzer(nextConfig);
    } catch {
        console.warn('Bundle analyzer not available. Run: npm install --save-dev @next/bundle-analyzer');
    }
}

module.exports = exportedConfig;
