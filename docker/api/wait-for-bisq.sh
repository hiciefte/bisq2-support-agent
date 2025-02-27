#!/bin/bash

echo "Waiting for Bisq service to be ready..."

# Function to check if Bisq API is responding
check_bisq() {
    curl -s "http://bisq:8082/api/v1/chat/messages" > /dev/null
    return $?
}

# Wait for Bisq to be ready
until check_bisq; do
    echo "Bisq service is not ready yet... waiting"
    sleep 10
done

echo "Bisq service is ready, starting FAQ extraction..."
python -m app.scripts.extract_faqs 