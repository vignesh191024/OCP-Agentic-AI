FROM python:3.9-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

# Force Python to print logs immediately
ENV PYTHONUNBUFFERED=1

EXPOSE 8080

# Run as non-root user
RUN useradd -ms /bin/bash appuser
USER appuser

# Use python directly to ensure logs flush and main block runs
CMD ["python", "main.py"]
