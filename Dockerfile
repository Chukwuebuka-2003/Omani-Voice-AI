# Use an official Python runtime as a parent image.
# Using a "slim" version reduces the final image size.
FROM python:3.12-slim

# Set the working directory inside the container to /app
WORKDIR /app

# Install system dependencies.
# This is the crucial step to install ffmpeg, which pydub requires.
# We update the package list, install ffmpeg, and then clean up to keep the image small.
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Copy the file that lists the Python dependencies into the container.
COPY requirements.txt .

# Install the Python dependencies.
# --no-cache-dir ensures pip doesn't store the downloaded packages, which keeps the image size smaller.
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of your application's code into the container's working directory.
COPY . .

# Tell Docker that the container listens on port 8080 at runtime.
# This must match the port your application is configured to use.
EXPOSE 8080

# Define the command to run when the container starts.
# This runs your FastAPI application using the Uvicorn server.
# It listens on all available network interfaces (0.0.0.0) on port 8080.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
