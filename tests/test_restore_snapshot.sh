#!/usr/bin/env bash

# Set up error handling
set -e

# Create test directory
TEST_DIR=$(mktemp -d)
cd "$TEST_DIR"

# Copy the example snapshot file from project root with a unique test name
cp ../test_resources/snapshot.example.json ./test_restore_snapshot_temporary.json

# Create a mock comfy command that simulates the real comfy behavior
cat > comfy << 'EOF'
#!/bin/bash
if [[ "$1" == "--workspace" && "$3" == "restore-snapshot" ]]; then
    # Verify the snapshot file exists
    if [[ ! -f "$4" ]]; then
        echo "Error: Snapshot file not found"
        exit 1
    fi
    echo "Mock: Restored snapshot from $4"
    exit 0
fi
EOF

chmod +x comfy
export PATH="$TEST_DIR:$PATH"

# Run the actual restore_snapshot script
echo "Testing snapshot restoration..."
../src/restore_snapshot.sh

# Verify the script executed successfully
if [ $? -eq 0 ]; then
    echo "✅ Test passed: Snapshot restoration script executed successfully"
else
    echo "❌ Test failed: Snapshot restoration script failed"
    exit 1
fi

# Clean up
rm -rf "$TEST_DIR"
rm -f ../test_restore_snapshot_temporary.json  # Remove the test snapshot file from root directory
  