# Bisq 2 Support Agent Web Frontend

This is a [Next.js](https://nextjs.org) project for the Bisq 2 Support Agent web interface.

## Features

- Modern chat interface with real-time interaction
- Support for rating responses and providing feedback
- Automatic source attribution for responses
- Responsive design that works on mobile and desktop

## Recent Updates

- Improved source display to deduplicate sources by type
- Enhanced error handling for API communication
- Better state management for chat history

## Getting Started

### Running with Docker (Recommended)

The easiest way to run the web frontend as part of the complete application stack is using Docker Compose from the **root directory** of the `bisq2-support-agent` project:

```bash
# For local development with hot reloading (uses docker-compose.local.yml)
./run-local.sh

# For production deployment (uses docker-compose.yml)
# Initial deployment is done via the main deploy.sh script
sudo /path/to/bisq2-support-agent/scripts/deploy.sh

# Subsequent updates are done via the main update.sh script
cd /opt/bisq-support # Or your installation directory
sudo ./scripts/update.sh
```

### Local Development (Standalone Web)

If you want to run *only* the web frontend directly (e.g., pointing to a separately running API):

```bash
cd web # Navigate to this directory

# Install dependencies
npm install

# Run the development server
npm run dev
```

Open [http://localhost:3000](http://localhost:3000) with your browser to see the result.

### Configuration

The web frontend needs to know where the API service is located. This is handled automatically by the Docker Compose setup (using Nginx reverse proxy at `/api`).

If running standalone (using `npm run dev`), you might need to configure the API URL via the `NEXT_PUBLIC_API_URL` environment variable if the API is not at the default location:

```bash
# Example for standalone development pointing to default API port
NEXT_PUBLIC_API_URL=http://localhost:8000 npm run dev
```

## Project Structure

- `src/app` - Next.js app router pages
- `src/components` - React components
  - `chat` - Chat interface components
  - `ui` - Common UI components
- `src/lib` - Utility functions
- `public` - Static assets

## Learn More

To learn more about Next.js, take a look at the following resources:

- [Next.js Documentation](https://nextjs.org/docs) - learn about Next.js features and API.
- [Learn Next.js](https://nextjs.org/learn) - an interactive Next.js tutorial.

## Contributing

If you want to contribute to this project, please follow the [style guide](../STYLE_GUIDE.md) and make sure to test your changes thoroughly.
