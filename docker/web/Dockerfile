# Stage 1: Dependencies & Build
FROM node:20-alpine@sha256:fb4cd12c85ee03686f6af5362a0b0d56d50c58a04632e6c0fb8363f609372293 AS builder

# Set working directory for build stage
WORKDIR /build

# Suppress npm notices to keep logs clean
RUN npm config set update-notifier false && \
  npm config set fund false

# Copy package files
COPY web/package*.json ./

# Install all dependencies with clean cache
RUN npm cache clean --force && \
  npm install

# Copy application code
# ⚠️ CRITICAL: This COPY instruction bakes code into the image
# Any changes to web/src/, web/app/, web/components/, web/lib/, web/styles/ require container REBUILD, not just restart
# The deployment script checks for these changes using needs_web_rebuild()
COPY web/ ./

# Set build arguments
ARG BUILD_ENV=production
ARG HOSTNAME
ARG NEXT_PUBLIC_API_URL
ARG BUILD_ID=bisq-support-build

# Set environment variables for build
ENV NODE_ENV=${BUILD_ENV}
ENV HOSTNAME=${HOSTNAME}
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}
ENV NEXT_BUILD_ID=${BUILD_ID}

# Build the application
RUN npm run build

# Keep only runtime dependencies in the artifact copied into the final image.
# hadolint ignore=DL3059
RUN npm prune --omit=dev

# Stage 2: Runtime
FROM node:20-alpine@sha256:fb4cd12c85ee03686f6af5362a0b0d56d50c58a04632e6c0fb8363f609372293

WORKDIR /app

# Upgrade vulnerable packages from the pinned Alpine release to exact fixed versions.
RUN apk add --no-cache \
  libcrypto3=3.5.7-r0 \
  libssl3=3.5.7-r0 && \
  rm -rf /usr/local/lib/node_modules/npm && \
  rm -f /usr/local/bin/npm /usr/local/bin/npx

# Copy built application, node_modules and next.config.js
COPY --from=builder /build/.next ./.next
COPY --from=builder /build/node_modules ./node_modules
COPY --from=builder /build/package.json ./package.json
COPY --from=builder /build/public ./public

# Set environment variables
ARG BUILD_ENV=production
ENV NODE_ENV=${BUILD_ENV}
ENV NEXT_TELEMETRY_DISABLED=1
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}
ENV PORT=3000

# Expose the port
EXPOSE 3000

# Run the application
CMD ["node", "node_modules/next/dist/bin/next", "start"]
