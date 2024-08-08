FROM  python:3.9.19-slim

WORKDIR /app

COPY requirements.txt requirements.txt

RUN pip install -r requirements.txt

# -v /path/to/data:/data
ENV DATA=/data

COPY app.py app.py

CMD ["python", "app.py"]
