# 1. Start with a official Python base "image"
FROM python:3.10-slim

# 2. Set an environment variable (good practice)
ENV PORT 8080

# 3. Set the "working directory" inside the container
WORKDIR /app

# 4. Copy our list of requirements and install them
COPY requirements.txt .
RUN pip install -r requirements.txt

# 5. Copy the rest of our app's code (main.py)
COPY . .

# 6. This is the command to run when the container starts
#    It tells gunicorn to run our "app" (from main.py)
CMD gunicorn --bind 0.0.0.0:$PORT --timeout 120 main:app
