#!/bin/bash

# Start Tor in the background
sudo -u debian-tor tor -f /etc/tor/torrc &

# Wait for Tor to start
echo "Waiting for Tor to start..."
sleep 10

# Start the Bisq2 API service
./gradlew :apps:http-api-app:run -Djava.awt.headless=true