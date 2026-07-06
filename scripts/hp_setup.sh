#!/usr/bin/env bash
# HP setup — run this on the 36GB RAM machine after llama4:scout finishes pulling.
# Clones the scout Modelfile repo and builds all hardened Ollama models.
set -euo pipefail

SCOUT_DIR="$HOME/scout"
REPO="https://github.com/notonelikeme-cmd/scout.git"

echo "=== AetherionGenesis HP Setup ==="
echo "Host: $(hostname)"
echo "Date: $(date)"
echo ""

# ── 1. Clone or update scout Modelfiles ──────────────────────────────────────
if [ -d "$SCOUT_DIR/.git" ]; then
  echo "[1/5] Updating scout Modelfiles..."
  git -C "$SCOUT_DIR" pull
else
  echo "[1/5] Cloning scout Modelfiles..."
  git clone "$REPO" "$SCOUT_DIR"
fi
echo "      Scout dir: $SCOUT_DIR"
echo ""

# ── 2. Verify base models are pulled ─────────────────────────────────────────
echo "[2/5] Checking base models..."
REQUIRED_MODELS=("llama4:scout" "qwen2.5-coder:14b" "deepseek-r1:14b" "gemma4:latest")
MISSING=()
for model in "${REQUIRED_MODELS[@]}"; do
  if ollama list | grep -q "^${model%:*}"; then
    echo "      ✓ $model"
  else
    echo "      ✗ $model — MISSING, pulling..."
    ollama pull "$model"
    MISSING+=("$model")
  fi
done
echo ""

# ── 3. Build hardened Ollama models ──────────────────────────────────────────
echo "[3/5] Building hardened models..."

cd "$SCOUT_DIR"

build_model() {
  local name="$1"
  local file="$2"
  if [ -f "$file" ]; then
    echo "      Building $name from $file..."
    ollama create "$name" -f "$file" && echo "      ✓ $name" || echo "      ✗ $name FAILED"
  else
    echo "      SKIP $name — $file not found"
  fi
}

build_model "scout"           "Modelfile"
build_model "scout-mem"       "Modelfile.mem"
build_model "scout-pm"        "polymarket/Modelfile.pm"
build_model "r1-sec"          "Modelfile.r1"
build_model "gemma4-sec"      "Modelfile.gemma"
build_model "qwen-sec"        "Modelfile.qwen"
build_model "scout-llama4"    "Modelfile.scout-llama4"
echo ""

# ── 4. Clone AetherionGenesis ─────────────────────────────────────────────────
AETHER_DIR="$HOME/AetherionGenesis"
AETHER_REPO="https://github.com/notonelikeme-cmd/AetherionGenesis.git"

echo "[4/5] AetherionGenesis..."
if [ -d "$AETHER_DIR/.git" ]; then
  echo "      Updating..."
  git -C "$AETHER_DIR" pull
else
  echo "      Cloning..."
  git clone "$AETHER_REPO" "$AETHER_DIR"
fi

# Install Python deps
echo "      Installing Python deps..."
pip install --quiet networkx numpy watchdog gitpython 2>&1 | tail -1
# faiss-cpu is large — install separately
pip install --quiet faiss-cpu 2>&1 | tail -1 || echo "      faiss-cpu skipped (optional)"
echo "      ✓ deps done"
echo ""

# ── 5. Smoke test kernel boot ─────────────────────────────────────────────────
echo "[5/5] Kernel boot smoke test..."
cd "$AETHER_DIR"
timeout 10 python3 -c "
from core.kernel import Kernel
k = Kernel()
k.bootstrap()
" && echo "      ✓ kernel boots clean" || echo "      ✗ kernel boot failed — check output above"

echo ""
echo "=== HP Setup Complete ==="
echo "Registered models:"
ollama list | grep -E "scout|r1-sec|gemma4-sec|qwen-sec"
echo ""
echo "To run the kernel as a service:"
echo "  cd ~/AetherionGenesis && python3 -m core.kernel"
echo ""
echo "To dispatch a pipeline from Python:"
echo "  from core.kernel import Kernel"
echo "  k = Kernel()"
echo "  k.bootstrap()   # in a thread"
echo "  k.dispatch('nexus.pipeline', {'hypothesis': '...', 'contract_path': '...', 'code': '...'})"
