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
        // Use a constant build ID to prevent version fingerprinting
        // This makes it harder for attackers to identify specific versions
        return 'bisq-support-build'
    },
    // Performance optimizations
    compress: true,
    reactStrictMode: true,
};

module.exports = nextConfig;
