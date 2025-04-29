# Use JDK 21 as base image
FROM eclipse-temurin:21-jdk

# Set working directory
WORKDIR /opt/bisq2

# Install git and other dependencies
RUN apt-get update && \
    apt-get install -y git && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Clone the specific branch from the forked repository
RUN git clone --recurse-submodules -b add-support-api https://github.com/hiciefte/bisq2.git .

# Build the application
RUN ./gradlew :apps:http-api-app:build

# Create a non-root user
RUN useradd -m -s /bin/bash bisq-support && \
    chown -R bisq-support:bisq-support /opt/bisq2

# Switch to non-root user
USER bisq-support

# Set environment variables
ENV BISQ_DATA_DIR=/opt/bisq2/data
ENV JAVA_OPTS="-Xmx1g"

# Copy custom configuration
COPY --chown=bisq-support:bisq-support config/http_api_app.conf /opt/bisq2/apps/http-api-app/src/main/resources/http_api_app.conf

# Expose the API port
EXPOSE 8090

# Start the API service
CMD ["./gradlew", ":apps:http-api-app:run", "-Djava.awt.headless=true"] 