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

# Expose the port
EXPOSE 3000

# Start the development server
CMD ["npm", "run", "dev"] 