# Use an official Python runtime as the base image
FROM python:3.9

# Set the working directory in the container
WORKDIR /app

# Install Selenium, Requests, and BeautifulSoup
RUN pip install selenium requests beautifulsoup4

# Copy the Python script to the container
COPY fetch.py .

# Set the volume to the current directory
VOLUME /app

# Run the Python script when the container launches
CMD ["python", "fetch.py"]
