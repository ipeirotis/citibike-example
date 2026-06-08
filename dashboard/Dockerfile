# Streamlit dashboard image for Cloud Run.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8080

WORKDIR /app

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY app.py ./
COPY .streamlit/ ./.streamlit/

EXPOSE 8080

# Cloud Run injects $PORT; bind it on all interfaces, headless. Shell form so
# ${PORT} is expanded at runtime.
CMD streamlit run app.py \
    --server.port=${PORT} \
    --server.address=0.0.0.0 \
    --server.headless=true \
    --server.enableCORS=false \
    --server.enableXsrfProtection=false
