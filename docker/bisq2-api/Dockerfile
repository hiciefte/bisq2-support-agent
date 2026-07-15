# ---- Builder Stage ----
FROM eclipse-temurin:21-jdk@sha256:1eeacc8c295ed4805f6ffead2417b1936aad296b02ea9e56b457230befc9e98d AS builder

# Define build arguments with defaults
ARG BISQ2_COMMIT=e1b45babafa45b5f4dbaabdf4dedec4b6de4d6ac
ARG BISQ2_REPO_URL=https://github.com/hiciefte/bisq2.git

WORKDIR /opt/bisq2

# Install git using --no-install-recommends
RUN apt-get update && \
    apt-get install -y --no-install-recommends git && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Fetch only the configured commit and verify that the server returned it.
RUN git init . && \
    git remote add origin "${BISQ2_REPO_URL}" && \
    git fetch --depth 1 origin "${BISQ2_COMMIT}" && \
    test "$(git rev-parse FETCH_HEAD)" = "${BISQ2_COMMIT}" && \
    git checkout --detach FETCH_HEAD && \
    git submodule update --init --recursive --depth 1

# Attempt to download dependencies using files cloned inside the container.
# Continue even if it fails (e.g., project structure changed).
RUN ./gradlew :apps:api-app:dependencies --no-daemon || echo "Dependency download step failed or project has no dependencies task, continuing build..."

# Build the application using installDist to create a distribution package
# Use --no-daemon to avoid leaving a Gradle daemon running
RUN ./gradlew :apps:api-app:installDist --no-daemon

# ---- Final Stage ----
# Use a smaller JRE image for the runtime environment
FROM eclipse-temurin:21-jre@sha256:d2b9f8f12212cadcfdf889461531784e8fd097feade954d65b31ee7a71c473ec

WORKDIR /opt/bisq2

# Install runtime dependencies: tor for networking, tini as an init process, gosu for user switching
# Add iproute2 for the 'ss' command (though not strictly needed now)
RUN apt-get update && \
    apt-get install -y --no-install-recommends tor tini iproute2 gosu && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Create /var/lib/tor for system tor package, though embedded Tor will use its own data dir.
# The 'debian-tor' user created by 'apt-get install tor' is important if the process drops privileges.
RUN mkdir -p /var/lib/tor && \
    chown -R debian-tor:debian-tor /var/lib/tor && \
    chmod 700 /var/lib/tor

# Create a non-root user and group with fixed UID/GID (matches deploy.sh recommendation)
ARG APP_UID=1001
ARG APP_GID=1001
RUN groupadd -g ${APP_GID} bisq-support && \
    useradd -m -d /home/bisq-support -u ${APP_UID} -g ${APP_GID} -s /bin/bash bisq-support

# Create essential directories
RUN mkdir -p /opt/bisq2/data /opt/bisq2/config

# Copy built application artifacts from the builder stage
# The installDist task typically puts outputs in build/install/<appName>
COPY --from=builder /opt/bisq2/apps/api-app/build/install/api-app /opt/bisq2/app

# Copy custom configuration file to the standard config location
COPY config/http_api_app.conf /opt/bisq2/config/http_api_app.conf

# Copy the startup script
COPY start.sh /opt/bisq2/start.sh

# Set ownership and permissions for application files and directories
# Ensure the non-root user can access/execute necessary files
RUN chown ${APP_UID}:${APP_GID} /opt/bisq2/data && \
    chown ${APP_UID}:${APP_GID} /opt/bisq2/config && \
    chown ${APP_UID}:${APP_GID} /opt/bisq2/config/http_api_app.conf && \
    chown -R ${APP_UID}:${APP_GID} /opt/bisq2/app && \
    chown ${APP_UID}:${APP_GID} /opt/bisq2/start.sh && \
    chmod +x /opt/bisq2/start.sh

# Set environment variables for the runtime
ENV BISQ_DATA_DIR=/opt/bisq2/data
ENV JAVA_OPTS="-Xmx1g"

# Expose the API port (no changes needed here)
EXPOSE 8090

# Use tini as the entrypoint to properly handle process signals (like SIGTERM)
ENTRYPOINT ["/usr/bin/tini", "--"]

# Set the default command to run the startup script
CMD ["/opt/bisq2/start.sh"]
