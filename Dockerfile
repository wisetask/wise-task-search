FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt ./requirements.txt

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY . /app/semantic_search_api

EXPOSE 8001
CMD ["uvicorn", "semantic_search_api.main:app", "--host", "0.0.0.0", "--port", "8001"]
