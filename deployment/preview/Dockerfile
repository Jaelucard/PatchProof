FROM python:3.13-slim@sha256:2d44738ebf4ce5f63b9d9ea871e9c7cfdc0426f7b0c97cac915fd88ded1d86bb

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/backend
WORKDIR /app
COPY python-runtime-lock.txt /app/python-runtime-lock.txt
RUN python -m pip install --no-cache-dir -r /app/python-runtime-lock.txt
COPY backend/ /app/backend/
COPY frontend/dist/ /app/frontend/dist/
COPY data/ /app/data/
COPY LICENSE REUSE.md /app/
USER 10001:10001
CMD ["python", "-B", "-m", "patchproof", "--database", "/data/review.sqlite3", "--port", "8770"]
