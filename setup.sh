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
echo "🐳 OPTION 1: Docker Compose (Recommended)"
echo "   For EPICS connectivity on macOS/Windows:"
echo "   cp docker/.env.example docker/.env"
echo "   # Edit docker/.env with your EPICS server IPs"
echo ""
echo "   Start the full distributed stack:"
echo "   cd docker && docker compose up --build"
echo ""
echo "   This starts:"
echo "   - PostgreSQL (port 5432)"
echo "   - Redis (port 6379)"
echo "   - API Server (port 8080)"
echo "   - PV Monitor (1 replica)"
echo "   - Workers (2 replicas)"
echo ""
echo "   Access the API at: http://localhost:8080"
echo "   Swagger docs at: http://localhost:8080/docs"
echo ""
echo "💻 OPTION 2: Local Development"
echo "   Run infrastructure in Docker, services locally:"
echo ""
echo "   1. Start PostgreSQL & Redis:"
echo "      cd docker && docker compose up -d db redis"
echo ""
echo "   2. Run database migrations:"
echo "      alembic upgrade head"
echo ""
echo "   3. (Optional) Load sample data:"
echo "      python -m scripts.seed_pvs --count 100"
echo ""
echo "   4. Start services (in separate terminals):"
echo "      uvicorn app.main:app --reload --port 8000    # API"
echo "      python -m app.monitor_main                    # Monitor"
echo "      arq app.worker.WorkerSettings                 # Worker"
echo ""
echo "📝 Note: Docker Compose project is named 'squirrel'"
echo "   Container names: squirrel-api, squirrel-db, etc."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
