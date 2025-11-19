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
};

module.exports = nextConfig;
