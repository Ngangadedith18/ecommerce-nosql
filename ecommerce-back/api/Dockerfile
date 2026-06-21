FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir \
    fastapi==0.111.0 \
    uvicorn[standard]==0.30.1 \
    pymongo==4.7.2 \
    motor==3.4.0 \
    neo4j==5.20.0 \
    redis==5.0.4 \
    pydantic==2.7.1

COPY main.py .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]