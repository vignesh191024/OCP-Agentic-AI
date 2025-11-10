FROM python:3.9-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

EXPOSE 8080

# Run as non-root user
RUN useradd -ms /bin/bash appuser
USER appuser

CMD ["flask", "run", "--host=0.0.0.0", "--port=8080"]

