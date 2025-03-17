# Use Node.js 20 as the base image
FROM node:20-alpine

# Set working directory
WORKDIR /app

# Copy package.json and package-lock.json
COPY web/package*.json ./

# Install dependencies
RUN npm ci

# Copy the rest of the application
COPY web/ ./

# Set build argument with default to development
ARG BUILD_ENV=development

# Set environment variable based on build arg
ENV NODE_ENV=${BUILD_ENV}

# Expose the port
EXPOSE 3000

# Use different commands based on environment
CMD if [ "$NODE_ENV" = "production" ]; then \
      npm run build && npm run start; \
    else \
      npm run dev; \
    fi 