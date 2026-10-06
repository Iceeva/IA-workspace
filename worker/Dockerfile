FROM python:3.12-slim
WORKDIR /srv
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app ./app
COPY worker/main.py ./worker_main.py
CMD ["python", "worker_main.py"]
