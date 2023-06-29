# Distributed Systems Coffee Shop

A small Flask project used to demonstrate core distributed-systems concepts ,
load balancing, health checks, rate limiting, and asynchronous message
processing, modeled around a toy "coffee shop" API.

The system is made up of several independent services that are composed
together with Docker Compose:

- **`app.py`**, the main Flask API server. Backed by MySQL, it exposes
  endpoints to create users, get/set a user's favorite coffee, and (as an
  admin) view a leaderboard of the most popular coffees. Each request is
  authenticated via HTTP Basic Auth against credentials stored in the
  database. Includes a simple in-memory token-bucket rate limiter, both
  per-user and per-IP. On user creation, a message is published to an AWS SQS
  queue.
- **`consumer.py`**, a worker that polls the SQS queue and processes
  messages (e.g. the "user created" notifications published by the API).
- **`load_balancer.py`**, a custom Flask-based reverse proxy that
  round-robins requests across a configurable, health-checked list of
  backend application instances. The list of registered applications is
  persisted as JSON in an S3 bucket and can be read/updated via
  `GET`/`POST /loadbalancer/apps`.
- **`docker/`**, Dockerfiles for the server, load balancer, consumer, a
  "guest" container, and MySQL, plus MySQL configuration.
- **`startserver.sh`** / **`myapp.service`**, a shell script and systemd
  unit for running the Flask server directly on an EC2 instance.

## Key technologies

- Python 3.9 / Flask
- MySQL (via `mysql-connector-python`)
- AWS SQS (`boto3`) for asynchronous processing
- AWS S3 (`boto3`) for storing load-balancer configuration
- Docker / Docker Compose for orchestrating the multi-service setup
- Pipenv for dependency management

## API overview (`app.py`, prefix `/v1`)

- `GET /v1/ping`, health check, returns which server instance answered.
- `POST /v1/user/create`, create a user (`username`, `password`); publishes
  a message to SQS.
- `GET|POST /v1/coffee/favourite`, get or set the authenticated user's
  favorite coffee (Basic Auth required; POST is rate-limited per IP).
- `GET /v1admin/coffee/favourite/leadeboard` (note: missing slash before `admin` in the route definition), admin-only endpoint returning
  the top 3 favorite coffees across all users (rate-limited per user).

## Installation instructions

1 - Install pipenv:

```bash
pip install pipenv
```

2 - Initialize the virtual environment and install the dependencies:

```bash
pipenv install
```

3 - Start the server on port 80:

```bash
pipenv run flask run --reload --host=0.0.0.0 --port=80
```

## Docker compose instructions

1 - Copy the .env.example file to .env:

```bash
cp .env.example .env
```

2 - Start docker compose:

```bash
docker compose up
```

This brings up three load-balanced app server instances (`server1.test`,
`server2.test`, `server3.test`), a `loadbalancer.test` service in front of
them, a `consumer` worker, a `guest` container, and a MySQL database.

Required environment variables (see `.env.example`): `DB_DATABASE`,
`DB_USERNAME`, `DB_PASSWORD`, `DB_HOST`, `AWS_DEFAULT_REGION`,
`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SQS_QUEUE_URL`,
`AWS_BUCKET_NAME`.

## Status

This is a learning/demo project exploring distributed systems patterns
(load balancing, health checks, rate limiting, message queues) rather than a
production application.
