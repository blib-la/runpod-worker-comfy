#!/usr/bin/env bash

# Set up error handling
set -e

# Store the path to the script we want to test
SCRIPT_TO_TEST="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/src/restore_snapshot.sh"

# Ensure the script exists and is executable
if [ ! -f "$SCRIPT_TO_TEST" ]; then
    echo "Error: Script not found at $SCRIPT_TO_TEST"
    exit 1
fi
chmod +x "$SCRIPT_TO_TEST"

# Create test directory
TEST_DIR=$(mktemp -d)
cd "$TEST_DIR"

# Create a minimal mock snapshot file
cat > test_restore_snapshot_temporary.json << 'EOF'
{
  "comfyui": "test-hash",
  "git_custom_nodes": {},
  "file_custom_nodes": [],
  "pips": {}
}
EOF

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
echo "Script location: $SCRIPT_TO_TEST"
"$SCRIPT_TO_TEST"

# Verify the script executed successfully
if [ $? -eq 0 ]; then
    echo "✅ Test passed: Snapshot restoration script executed successfully"
else
    echo "❌ Test failed: Snapshot restoration script failed"
    exit 1
fi

# Clean up
rm -rf "$TEST_DIR"
  