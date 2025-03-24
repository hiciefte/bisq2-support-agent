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

The easiest way to run the web frontend is using Docker Compose from the root directory:

```bash
# For development with hot reload
./run-local.sh

# For production
./run-cloud.sh
```

### Local Development

If you want to run the web frontend directly:

```bash
# Install dependencies
npm install

# Run the development server
npm run dev
```

Open [http://localhost:3000](http://localhost:3000) with your browser to see the result.

### Configuration

The web frontend is configured to communicate with the API service. By default, it will use the host's hostname to determine the API URL.

You can override the API URL by setting the `NEXT_PUBLIC_API_URL` environment variable:

```bash
# For development
NEXT_PUBLIC_API_URL=http://localhost:8000 npm run dev
```

In Docker, this is configured in the `docker/.env` file and Docker Compose configurations.

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
