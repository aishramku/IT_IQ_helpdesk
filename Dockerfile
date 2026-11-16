# TriageIQ - one image, two roles (api | dashboard | setup), selected by the compose `command`.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

# all dependencies are pinned in requirements.txt (includes the spaCy model wheel)
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
EXPOSE 8000 8501

# default: API. Build artefacts (model, DB) are created by the `setup` service in docker-compose.yml.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
