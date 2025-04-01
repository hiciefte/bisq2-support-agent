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
    // Configure asset prefix to use the server's hostname
    // In production, use the HOSTNAME environment variable
    // In development, use an empty string to allow Next.js to handle assets locally
    assetPrefix: process.env.NODE_ENV === "production"
        ? `http://${process.env.HOSTNAME}`
        : "",
    // Ensure proper handling of static assets
    poweredByHeader: false,
    compress: true,
    reactStrictMode: true,
};

export default nextConfig;
