# Use an official Python runtime as a parent image
#FROM python:3.9
FROM python:alpine3.18

# Set the working directory to /app
WORKDIR /app

# Copy the current directory contents into the container at /app
COPY . /app

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Make port 80 available to the world outside this container
# EXPOSE 80

# Define environment variable
ENV PYTHONPATH /app/src
ENV PROMETHEUS_URL "http://localhost:9090"

# Run app.py when the container launches
CMD ["python", "-m", "src.k8soptimizer.main"]

USER nobody
