# Stage 1: Dependencies & Build
FROM node:20-alpine AS builder

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

# Set build argument
ARG BUILD_ENV=production
ARG HOSTNAME
ARG NEXT_PUBLIC_API_URL
ENV NODE_ENV=${BUILD_ENV}
ENV HOSTNAME=${HOSTNAME}
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}

# Build the application
RUN npm run build

# Stage 2: Runtime
FROM node:20-alpine

WORKDIR /app

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
CMD ["npm", "run", "start"]
