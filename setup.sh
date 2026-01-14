#!/bin/bash

# Setup script for Squirrel Backend

set -e  # Exit on error

echo "🐿️  Squirrel Backend Setup"
echo ""

# Check if we should use conda or venv
if command -v conda &> /dev/null; then
    echo "📦 Using Conda for environment management..."
    conda create -n squirrel python=3.11 -y
    echo ""
    echo "Activating environment..."
    source "$(conda info --base)/etc/profile.d/conda.sh"
    conda activate squirrel
else
    echo "📦 Using venv for environment management..."
    python3 -m venv venv
    source venv/bin/activate
fi

echo ""
echo "📥 Installing dependencies..."
pip install -e ".[dev]"

echo ""
echo "⚙️  Copying environment template..."
if [ ! -f .env ]; then
    cp .env.example .env
    echo "Created .env file (please edit if needed)"
else
    echo ".env already exists, skipping"
fi

echo ""
echo "✅ Setup complete!"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Next steps:"
echo ""
echo "1. Start infrastructure (PostgreSQL & Redis):"
echo "   cd docker && docker-compose up -d db redis"
echo ""
echo "2. Run database migrations:"
echo "   alembic upgrade head"
echo ""
echo "3. (Optional) Load sample data:"
echo "   python -m scripts.seed_pvs --count 1000"
echo ""
echo "4. Start the services:"
echo "   uvicorn app.main:app --reload --port 8000      # API Server"
echo "   python -m app.monitor_main                      # PV Monitor"
echo "   arq app.worker.WorkerSettings                   # Worker"
echo ""
echo "Or use Docker Compose for everything:"
echo "   cd docker && docker-compose up --build"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
