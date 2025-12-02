FROM python:3.9-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

ENV PYTHONUNBUFFERED=1
EXPOSE 8080

RUN useradd -ms /bin/bash appuser
USER appuser

CMD ["python", "main.py"]
