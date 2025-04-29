# Use JDK 21 as base image
FROM eclipse-temurin:21-jdk

# Set working directory
WORKDIR /opt/bisq2

# Install git, tor, and other dependencies
RUN apt-get update && \
    apt-get install -y git tor && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Configure Tor
RUN mkdir -p /var/lib/tor && \
    chown -R debian-tor:debian-tor /var/lib/tor && \
    chmod 700 /var/lib/tor

# Create a basic Tor configuration
RUN echo "SocksPort 9050" > /etc/tor/torrc && \
    echo "ControlPort 9051" >> /etc/tor/torrc && \
    echo "DataDirectory /var/lib/tor" >> /etc/tor/torrc && \
    echo "Log notice stdout" >> /etc/tor/torrc

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
ENV TOR_BINARY_PATH=/usr/bin/tor

# Copy custom configuration
COPY --chown=bisq-support:bisq-support config/http_api_app.conf /opt/bisq2/apps/http-api-app/src/main/resources/http_api_app.conf

# Expose the API port
EXPOSE 8090

# Create a startup script
COPY --chown=bisq-support:bisq-support start.sh /opt/bisq2/start.sh
RUN chmod +x /opt/bisq2/start.sh

# Start the API service using the script
CMD ["/opt/bisq2/start.sh"] 