
FROM python:3.12-slim

WORKDIR /app

COPY sample_app.py .

RUN pip install --no-cache-dir flask

EXPOSE 5001

CMD ["python", "sample_app.py"]
