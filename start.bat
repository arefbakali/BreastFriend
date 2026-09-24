@echo off
REM Installe (si besoin), compile le frontend et lance BreastFriend sur http://127.0.0.1:5000
cd /d "%~dp0backend"
if not exist .venv python -m venv .venv
call .venv\Scripts\activate
pip install -q -r requirements.txt
REM Modeles locaux (bge-m3 + reranker, ~2 Go de PyTorch). Pour un mode 100 %% API : set SKIP_LOCAL_ML=1
if not "%SKIP_LOCAL_ML%"=="1" pip install -q -r requirements-local-ml.txt
if not exist .env copy .env.example .env
cd ..\frontend
if not exist node_modules call npm install
call npm run build
cd ..\backend
python -m rag.selfcheck
echo BreastFriend -^> http://127.0.0.1:5000
python app.py
