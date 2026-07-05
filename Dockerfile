# Official Python runtime base image
FROM python:3.10-slim

# Working directory set kar rahe hain
WORKDIR /app

# FFmpeg install karna (Render docker environment ke liye zaroori)
RUN apt-get update && \
    apt-get install -y ffmpeg && \
    rm -rf /var/lib/apt/lists/*

# Requirements file copy aur packages install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Baaki saara code copy karna
COPY . .

# Ensure directories exist
RUN mkdir -p songs temp_files fonts

# Bot ko run karne ki command
CMD ["python", "main.py"]
