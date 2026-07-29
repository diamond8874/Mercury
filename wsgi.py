"""
Production WSGI entry point.

    waitress-serve --host=0.0.0.0 --port=5000 --threads=8 wsgi:application
    gunicorn --workers 1 --threads 8 --timeout 300 --bind 0.0.0.0:5000 wsgi:application

**Run a single worker process with multiple threads.**

Mercury's pipeline uses in-process background threads plus a per-session
``threading.Event`` handshake. Job state is mirrored to disk so a poll that
lands elsewhere still reads the right status, but the handshake itself is
in-process: with several worker processes an analysis could wait out its
timeout instead of being woken instantly. Threads give the same concurrency
here anyway, because the heavy work (pandas, network I/O) releases the GIL.

Scale by running more containers behind a load balancer with sticky sessions,
or move job state to Redis (see DEPLOYMENT.md).
"""

from app import create_app

application = create_app()

# Some hosts look for `app` rather than `application`.
app = application
