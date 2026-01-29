#!/bin/bash
# Manual hyperparameter optimization workflow
# This script iterates through configurations, restarting the API each time
#
# Usage: ./run_manual_optimization.sh
# Run from project root

set -e

COMPOSE_CMD="docker compose -f docker/docker-compose.yml -f docker/docker-compose.local.yml"
ENV_FILE="docker/.env"
ENV_FILE_BACKUP="${ENV_FILE}.optimization_backup"
RESULTS_DIR="api/data/evaluation/optimization"

# Configurations to test: "semantic_weight,keyword_weight,description"
CONFIGS=(
    "0.7,0.3,current_default"
    "0.6,0.4,more_keyword"
    "0.5,0.5,balanced"
    "0.8,0.2,more_semantic"
)

# Cleanup function to restore original config
cleanup() {
    echo ""
    echo "Cleaning up..."
    if [ -f "$ENV_FILE_BACKUP" ]; then
        echo "Restoring original configuration from backup..."
        mv "$ENV_FILE_BACKUP" "$ENV_FILE"
    fi
    # Remove any leftover .bak files from sed
    rm -f "${ENV_FILE}.bak"
    # Restart API with restored config
    echo "Restarting API with original configuration..."
    $COMPOSE_CMD up -d api --force-recreate
    echo "Cleanup complete."
}

# Register cleanup on script exit, interrupt, or termination
trap cleanup EXIT INT TERM

mkdir -p "$RESULTS_DIR"

# Always backup original env file before making changes (refresh on each run)
echo "Backing up original configuration..."
if ! cp -f "$ENV_FILE" "$ENV_FILE_BACKUP"; then
    echo "ERROR: Failed to create backup of $ENV_FILE"
    exit 1
fi

echo "=========================================="
echo "Manual Hyperparameter Optimization"
echo "=========================================="
echo "Testing ${#CONFIGS[@]} configurations"
echo ""

wait_for_api() {
    echo "Waiting for API to be ready (inside container)..."
    for i in {1..60}; do
        # Check health from inside the container
        if $COMPOSE_CMD exec -T api curl -s http://127.0.0.1:8000/health > /dev/null 2>&1; then
            echo "API ready!"
            # Wait a bit more for full initialization
            sleep 5
            return 0
        fi
        echo "  Attempt $i/60 - waiting..."
        sleep 5
    done
    echo "ERROR: API failed to become ready"
    return 1
}

for config in "${CONFIGS[@]}"; do
    IFS=',' read -r semantic keyword desc <<< "$config"

    echo ""
    echo "------------------------------------------"
    echo "Testing: $desc (semantic=$semantic, keyword=$keyword)"
    echo "------------------------------------------"

    # Update environment (handle both existing and missing keys)
    if grep -q "^HYBRID_SEMANTIC_WEIGHT=" "$ENV_FILE"; then
        sed -i.bak "s/^HYBRID_SEMANTIC_WEIGHT=.*/HYBRID_SEMANTIC_WEIGHT=$semantic/" "$ENV_FILE"
    else
        echo "HYBRID_SEMANTIC_WEIGHT=$semantic" >> "$ENV_FILE"
    fi
    if grep -q "^HYBRID_KEYWORD_WEIGHT=" "$ENV_FILE"; then
        sed -i.bak "s/^HYBRID_KEYWORD_WEIGHT=.*/HYBRID_KEYWORD_WEIGHT=$keyword/" "$ENV_FILE"
    else
        echo "HYBRID_KEYWORD_WEIGHT=$keyword" >> "$ENV_FILE"
    fi
    rm -f "${ENV_FILE}.bak"

    # Restart API with new config
    echo "Restarting API..."
    $COMPOSE_CMD up -d api --force-recreate

    # Wait for API to be ready (inside container)
    if ! wait_for_api; then
        echo "Skipping $desc due to API failure"
        continue
    fi

    # Run evaluation
    echo "Running RAGAS evaluation..."
    $COMPOSE_CMD exec -T api python -m app.scripts.run_ragas_evaluation \
        --samples /data/evaluation/bisq2_realistic_qa_samples.json \
        --output "/data/evaluation/optimization/${desc}_evaluation.json" \
        --backend qdrant

    echo "Completed: $desc"
done

# Cleanup will be called automatically via trap
echo ""
echo "=========================================="
echo "Optimization Complete!"
echo "Results saved to: $RESULTS_DIR"
echo "=========================================="
echo ""
echo "Compare results with:"
echo "  for f in $RESULTS_DIR/*_evaluation.json; do echo \"=== \$f ===\"; jq '.metrics' \"\$f\"; done"
