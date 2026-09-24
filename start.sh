#!/usr/bin/env bash
# Installe (si besoin), compile le frontend et lance BreastFriend sur http://127.0.0.1:5000
set -e
cd "$(dirname "$0")"
cd backend
[ -d .venv ] || python3 -m venv .venv
source .venv/bin/activate
pip install -q -r requirements.txt
# Modèles locaux (bge-m3 + reranker, ~2 Go de PyTorch). Mode 100 % API : SKIP_LOCAL_ML=1 ./start.sh
[ "${SKIP_LOCAL_ML:-0}" = "1" ] || pip install -q -r requirements-local-ml.txt
[ -f .env ] || cp .env.example .env
cd ../frontend
[ -d node_modules ] || npm install
npm run build
cd ../backend
python -m rag.selfcheck || echo "(certains composants ne sont pas prêts : voir ci-dessus)"
echo "BreastFriend -> http://127.0.0.1:5000"
python app.py
