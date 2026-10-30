FROM caddy:2.11.7-alpine@sha256:eb4d35b7452d1ab6171fbdbe8d9275b2301dad6dad92115d91e19fb9b24d510f AS gateway
USER 0
RUN setcap -r /usr/bin/caddy

FROM python:3.13-slim@sha256:2d44738ebf4ce5f63b9d9ea871e9c7cfdc0426f7b0c97cac915fd88ded1d86bb
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/backend PORT=8780
WORKDIR /app
COPY python-runtime-lock.txt /app/python-runtime-lock.txt
RUN python -m pip install --no-cache-dir -r /app/python-runtime-lock.txt
COPY --from=gateway /usr/bin/caddy /usr/local/bin/caddy
COPY backend/ /app/backend/
COPY frontend/dist/ /app/frontend/dist/
COPY data/ /app/data/
COPY deployment/hosted/runtime.py deployment/hosted/index.html /app/deployment/hosted/
COPY deployment/preview/Caddyfile.template deployment/preview/gateway-entrypoint.sh /app/deployment/preview/
COPY docs/evidence/live-diagnostic-2026-10-29.json docs/evidence/live-diagnostic-2026-10-29.md /app/docs/evidence/
COPY LICENSE REUSE.md /app/
# Render secret files are group-readable by group 1000. Runtime copies are 0600.
# The platform mount can replace /data ownership; runtime deliberately fails
# closed if UID 10001 cannot write it. Do not add a privileged runtime fallback.
RUN mkdir /data && chown 10001:1000 /data
USER 10001:1000
EXPOSE 8780
CMD ["python", "-B", "/app/deployment/hosted/runtime.py"]
