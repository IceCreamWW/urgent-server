FROM python:3.5.10-slim
 
WORKDIR /worker/
 
COPY requirements.txt requirements.txt
RUN pip install -r requirements.txt

# Copy our actual code
COPY celeryconfig.py celeryconfig.py
COPY worker.py worker.py

# Run it
CMD celery -A worker worker -l info -Q compute-worker -n compute-worker%h -Ofast -Ofair --pool=threads --concurrency=10
