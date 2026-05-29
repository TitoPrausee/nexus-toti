#!/bin/bash
# NEXUS Multi-Agent Framework — Setup Script
# Installs dependencies and verifies the environment

set -e

echo "═══════════════════════════════════════════════════"
echo "  NEXUS Multi-Agent Framework — Setup"
echo "  GLM Powered · Hermes-Inspired · v1.0"
echo "═══════════════════════════════════════════════════"
echo ""

# Check Python
if command -v python3 &>/dev/null; then
    PYTHON=python3
elif command -v python &>/dev/null; then
    PYTHON=python
else
    echo "ERROR: Python 3 not found. Install Python 3.10+ first."
    exit 1
fi

echo "✓ Python: $($PYTHON --version)"

# Check z-ai CLI
if command -v z-ai &>/dev/null; then
    echo "✓ z-ai CLI: $(which z-ai)"
else
    echo "ERROR: z-ai CLI not found. This is required for GLM access."
    exit 1
fi

# Install Python dependencies
echo ""
echo "Installing Python dependencies..."
$PYTHON -m pip install --quiet rich pyyaml 2>/dev/null || pip install --quiet rich pyyaml
echo "✓ Core dependencies installed"

# Optional: Telegram bot
echo ""
read -p "Install Telegram bot support? (y/N): " INSTALL_TG
if [[ "$INSTALL_TG" =~ ^[Yy]$ ]]; then
    $PYTHON -m pip install --quiet python-telegram-bot 2>/dev/null || pip install --quiet python-telegram-bot
    echo "✓ python-telegram-bot installed"
else
    echo "⊘ Telegram support skipped (install later with: pip install python-telegram-bot)"
fi

# Create memory directories
echo ""
mkdir -p memory/{sessions,skills,longterm} data/checkpoints
echo "✓ Memory directories created"

# Test LLM connection
echo ""
echo "Testing GLM connection..."
TEST_OUTPUT=$(z-ai chat -p "Say: NEXUS ready" -o /tmp/nexus_test.json 2>&1)
if [ $? -eq 0 ]; then
    echo "✓ GLM API connection working"
    rm -f /tmp/nexus_test.json
else
    echo "⚠ GLM API test failed. Check z-ai configuration."
fi

# Install default skills
echo ""
echo "Installing default skills..."
$PYTHON -c "
import json, os
skills = {
    'web_research': {'pattern': 'Use SCOUT with web_search, triangulate 2+ sources, confidence scoring', 'description': 'Web research with source triangulation'},
    'code_debug': {'pattern': 'Use FORGE with error_root_cause skill. Read error, identify cause, fix, validate.', 'description': 'Debug code by root cause analysis'},
    'data_extraction': {'pattern': 'Use SCOUT for raw data, FORGE for processing, HERALD for formatting', 'description': 'Extract and process data from sources'},
    'code_review': {'pattern': 'Use LENS with devil_advocate and failure_mode_analysis skills', 'description': 'Critical code review with structured verdict'},
    'task_planning': {'pattern': 'Decompose into DAG, parallel independent tasks, sequential dependencies', 'description': 'Plan complex multi-step tasks'},
}
skill_dir = 'memory/skills'
os.makedirs(skill_dir, exist_ok=True)
for name, data in skills.items():
    data['updated'] = 1700000000
    with open(os.path.join(skill_dir, f'{name}.json'), 'w') as f:
        json.dump(data, f, indent=2)
print(f'✓ {len(skills)} default skills installed')
"

echo ""
echo "═══════════════════════════════════════════════════"
echo "  NEXUS Setup Complete!"
echo ""
echo "  Usage:"
echo "    python3 nexus.py                     # Interactive CLI"
echo "    python3 nexus.py -t 'research AI'    # Single task"
echo "    python3 nexus.py --telegram          # Telegram bot"
echo ""
echo "  Set Telegram token:"
echo "    export NEXUS_TG_TOKEN='your-bot-token'"
echo "═══════════════════════════════════════════════════"
