# Phase 13 – Step 1: production image of the Streamlit app (runs locally and on Cloud Run).
# Build: docker build -t agentsville .
# Run:   docker run --rm -p 8080:8080 --env-file .env agentsville   → http://localhost:8080
FROM python:3.11-slim

# No .pyc files, unbuffered logs (Cloud Logging sees lines immediately), lean pip.
# PORT is set by Cloud Run at runtime; 8080 is the local default.
# Cloud Run's disk is temporary, so no local run log (Phase 14 sends runs to Cloud Logging);
# feedback goes to stdout → Cloud Logging (Phase 13 – Step 2).
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8080 \
    AGENTSVILLE_RUN_LOG=off \
    AGENTSVILLE_FEEDBACK_LOG=stdout

WORKDIR /app

# Dependencies first: this layer is cached until requirements.txt changes.
# Runtime deps only – pytest/ruff (requirements-dev.txt) never reach production.
COPY requirements.txt .
RUN pip install -r requirements.txt

# Only what the app runs (.dockerignore enforces the same list).
COPY .streamlit/ .streamlit/
COPY data/ data/
COPY prompts/ prompts/
COPY agentsville/ agentsville/
COPY app.py .

# Code stays owned by root (read-only for the app); the app runs as an unprivileged user.
RUN useradd --create-home --uid 10001 appuser
USER appuser

EXPOSE 8080

# Shell form via sh -c so ${PORT} is expanded at start-up; exec makes streamlit PID 1,
# so Cloud Run's SIGTERM reaches it directly.
CMD ["sh", "-c", "exec streamlit run app.py --server.port=${PORT} --server.address=0.0.0.0"]
