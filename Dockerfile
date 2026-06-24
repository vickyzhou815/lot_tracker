# Dockerfile - blueprint for building our app's image.
# Each instruction below creates one "layer" in the final image.
# Docker caches layers, so ordering matters: put things that change
# RARELY (like installing dependencies) BEFORE things that change
# OFTEN (like our actual app code) - that way, editing app/main.py
# doesn't force Docker to re-download all our Python packages again.

# FROM: start from an existing base image rather than building an
# operating system from scratch. python:3.12-slim is an official
# image maintained by the Python project itself - "slim" means a
# smaller, trimmed-down Linux base (less disk space, faster builds)
# compared to the full default image.
FROM python:3.12-slim

# WORKDIR: every instruction after this runs "inside" this folder
# path within the image's filesystem - similar to running `cd` once
# and having every following command operate relative to it.
WORKDIR /app

# Copy ONLY requirements.txt first (not the whole project yet).
# This is the caching trick mentioned above: as long as
# requirements.txt hasn't changed, Docker reuses the cached result
# of the pip install step below on the next build, instead of
# re-running it - a real time-saver once this project grows.
COPY requirements.txt .

# RUN: executes a command INSIDE the image while building it (not
# when the container later starts - this happens once, at build
# time). --no-cache-dir keeps the image smaller by not keeping pip's
# download cache around afterward, which we'll never need again
# inside the image.
RUN pip install --no-cache-dir -r requirements.txt

# Now copy the rest of our actual application code. This happens
# AFTER the pip install on purpose, per the caching note above.
COPY app/ ./app/

# EXPOSE: documents which port this container listens on. This line
# is informational/documentation only - it does NOT actually publish
# the port to your host machine. That happens via `docker run -p`,
# which we'll use in a moment.
EXPOSE 8000

# CMD: the command that runs when a container starts FROM this
# image. Unlike RUN above (build time), this runs every time you
# start a new container. We bind to 0.0.0.0 (not 127.0.0.1) so the
# server accepts connections from outside the container, not just
# from within it.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
