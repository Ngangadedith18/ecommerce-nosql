FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir \
    pandas==2.2.2 \
    pymongo==4.7.2 \
    neo4j==5.20.0 \
    redis==5.0.4

COPY clean_and_inject.py .

CMD ["python", "clean_and_inject.py"]