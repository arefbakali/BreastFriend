# Étape 1 : compilation du frontend
FROM node:20-slim AS front
WORKDIR /front
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# Étape 2 : backend Python (+ Tesseract français et Poppler pour l'OCR)
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr tesseract-ocr-fra poppler-utils libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app/backend
COPY backend/requirements.txt backend/requirements-local-ml.txt ./
ARG INSTALL_LOCAL_ML=true
RUN pip install --no-cache-dir -r requirements.txt \
    && if [ "$INSTALL_LOCAL_ML" = "true" ]; then \
         pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
         && pip install --no-cache-dir -r requirements-local-ml.txt; fi
COPY backend/ ./
COPY --from=front /front/dist /app/frontend/dist
ENV FRONTEND_DIST=/app/frontend/dist PYTHONUNBUFFERED=1
EXPOSE 5000
CMD ["python", "app.py"]
