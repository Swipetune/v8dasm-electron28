#!/bin/bash
# V8 12.8.374 v8dasm rebuild script
# After fixing sandbox flag and API patches

set -e

echo "=== V8DASM Rebuild Script ==="
echo "Target: V8 12.8.374 with Sandbox ENABLED"
echo ""

# Check Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "ERROR: Docker is not running. Please start Docker Desktop."
    exit 1
fi

echo "[1/4] Building Docker image (this takes 2-3 hours first time)..."
echo "      Using ccache for faster rebuilds..."

docker build \
    --progress=plain \
    -t v8dasm:12.8.374 \
    . 2>&1 | tee docker-rebuild-$(date +%Y%m%d-%H%M%S).log

echo ""
echo "[2/4] Extracting v8dasm binary..."
CONTAINER_ID=$(docker create v8dasm:12.8.374)
docker cp $CONTAINER_ID:/usr/local/bin/v8dasm ./v8dasm-new
docker rm $CONTAINER_ID

echo ""
echo "[3/4] Verifying binary..."
file ./v8dasm-new
chmod +x ./v8dasm-new

echo ""
echo "[4/4] Quick test..."
# Test with a simple invocation
./v8dasm-new 2>&1 || echo "(Expected: Usage message or error - binary runs!)"

echo ""
echo "=== BUILD COMPLETE ==="
echo "Binary: ./v8dasm-new"
echo ""
echo "To test on main.jsc:"
echo "  ./v8dasm-new /path/to/main.jsc > output.txt 2>&1"
echo ""
echo "To use with view8.py:"
echo "  python3 view8.py main.jsc output.js --path ./v8dasm-new"
