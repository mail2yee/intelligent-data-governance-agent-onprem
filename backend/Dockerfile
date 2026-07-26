# TODO: once building inside the company network, point this at the
# internal registry mirror's copy of this image instead of Docker Hub
# directly (e.g. internal-registry.company.internal/python:3.11-slim) -
# exact hostname/path unconfirmed, ask IT.
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
