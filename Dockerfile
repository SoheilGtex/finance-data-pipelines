# Minimal Dockerfile (dev/demo)
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-dev.txt

COPY . .
CMD ["python", "-m", "fdp.cli", "run-all"]
