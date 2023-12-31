from flask import Flask, Blueprint, jsonify, request
import base64
import os
import mysql.connector
import boto3
import threading


sqs_client = boto3.client(
    "sqs",
    region_name=os.environ.get("AWS_DEFAULT_REGION"),
    aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
)

app = Flask(__name__)

apiv1 = Blueprint("v1", __name__, url_prefix="/v1")

config = {
    "user": os.environ.get("DB_USERNAME"),
    "password": os.environ.get("DB_PASSWORD"),
    "host": os.environ.get("DB_HOST"),
    "database": os.environ.get("DB_DATABASE"),
    "port": "3306",
}

conn = mysql.connector.connect(**config)

cursor = conn.cursor()

cursor.execute(
    "CREATE TABLE IF NOT EXISTS users (id INT NOT NULL PRIMARY KEY AUTO_INCREMENT, is_admin BOOLEAN, username VARCHAR(255), password VARCHAR(255), favorite_coffee VARCHAR(255))"
)

seed = [
    {
        "id": 1,
        "username": "user1",
        "is_admin": True,
        "password": "password1",
        "favorite_coffee": "cappuccino",
    },
    {
        "id": 2,
        "username": "user2",
        "is_admin": True,
        "password": "password2",
        "favorite_coffee": "latte",
    },
    {
        "id": 3,
        "username": "user3",
        "is_admin": False,
        "password": "password3",
        "favorite_coffee": "espresso",
    },
    {
        "id": 4,
        "username": "user4",
        "is_admin": False,
        "password": "password4",
        "favorite_coffee": "mocha",
    },
    {
        "id": 5,
        "username": "user5",
        "is_admin": False,
        "password": "password5",
        "favorite_coffee": "americano",
    },
]

user_token_bucket = {}
ip_token_bucket = {}

for user in seed:
    cursor.execute("SELECT * FROM users WHERE id = %s", (user["id"],))

    if cursor.fetchone() is None:
        cursor.execute(
            "INSERT INTO users (is_admin, username, password, favorite_coffee) VALUES (%s, %s, %s, %s)",
            (
                user["is_admin"],
                user["username"],
                user["password"],
                user["favorite_coffee"],
            ),
        )

        conn.commit()


def get_user(auth_header):
    cursor = conn.cursor()

    if not auth_header or not auth_header.startswith("Basic "):
        return None
    auth_string = base64.b64decode(auth_header[6:]).decode("utf-8")
    user, password = auth_string.split(":")

    cursor.execute("SELECT * FROM users WHERE username = %s", (user,))

    data = cursor.fetchone()

    if data is None or password != data[3]:
        return None

    conn.commit()

    return user, data[1]


@apiv1.route("/ping", methods=["GET"])
def hello_world():
    return "server " + os.environ.get("SERVER_ID") + " response: pong"


@apiv1.route("/user/create", methods=["POST"])
def create_user():
    cursor = conn.cursor()

    if (
        not request.json
        or not "username" in request.json
        or not "password" in request.json
    ):
        return jsonify({"error": "Bad request"}), 400

    cursor.execute(
        "SELECT * FROM users WHERE username = %s", (request.json["username"],)
    )

    if cursor.fetchone() is not None:
        return jsonify({"error": "Username already exists"}), 400

    cursor.execute(
        "INSERT INTO users (is_admin, username, password, favorite_coffee) VALUES (%s, %s, %s, %s)",
        (False, request.json["username"], request.json["password"], ""),
    )

    conn.commit()

    queue_url = os.environ.get("AWS_SQS_QUEUE_URL")

    sqs_client.send_message(
        QueueUrl=queue_url,
        MessageBody=f"User \"{request.json['username']}\" was created",
    )

    return jsonify({"data": {"username": request.json["username"]}}), 200


@apiv1.route("/coffee/favourite", methods=["GET", "POST"])
def favourite_coffee():
    cursor = conn.cursor()

    user, is_admin = get_user(request.headers.get("Authorization"))

    if user is None:
        return jsonify({"error": "Unauthenticated"}), 401

    if request.method == "GET":
        cursor.execute("SELECT * FROM users WHERE username = %s", (user,))

        data = cursor.fetchone()

        conn.commit()

        return jsonify({"data": {"favouriteCofee": data[4]}}), 200

    elif request.method == "POST":
        if not request.json or not "favouriteCofee" in request.json:
            return jsonify({"error": "Bad request"}), 400

        ip_address = request.headers.get("X-Forwarded-For", request.remote_addr)

        if not rate_limit_ip(ip_address):
            return jsonify({"error": "Too many requests"}), 429

        cursor.execute(
            "UPDATE users SET favorite_coffee = %s WHERE username = %s",
            (request.json["favouriteCofee"], user),
        )

        conn.commit()

        cursor.execute("SELECT * FROM users WHERE username = %s", (user,))

        data = cursor.fetchone()

        conn.commit()

        return jsonify({"data": {"favouriteCofee": data[4]}}), 200


@apiv1.route("admin/coffee/favourite/leadeboard", methods=["GET"])
def top_favourite_coffee():
    cursor = conn.cursor()

    user, is_admin = get_user(request.headers.get("Authorization"))

    if user is None or not is_admin:
        return jsonify({"error": "Unauthenticated"}), 401

    if not rate_limit(user):
        return jsonify({"error": "Too many requests"}), 429

    coffee_count = {}

    cursor.execute("SELECT * FROM users")

    users = cursor.fetchall()

    for user in users:
        coffee = user[4]
        if coffee in coffee_count:
            coffee_count[coffee] += 1
        else:
            coffee_count[coffee] = 1

    top_coffee = sorted(coffee_count, key=coffee_count.get, reverse=True)[:3]

    conn.commit()

    return jsonify({"data": {"top3": top_coffee}}), 200


def reset_rate_limit(user):
    user_token_bucket[user] = 3


def rate_limit(user):
    if user_token_bucket.get(user) is None:
        user_token_bucket[user] = 3

    if user_token_bucket[user] == 0:
        return False

    user_token_bucket[user] -= 1

    if user_token_bucket[user] == 0:
        timer = threading.Timer(60, reset_rate_limit, [user])
        timer.start()

    return True


def reset_rate_limit_ip(ip):
    ip_token_bucket[ip] = 10


def rate_limit_ip(ip):
    if ip_token_bucket.get(ip) is None:
        ip_token_bucket[ip] = 10

    if ip_token_bucket[ip] == 0:
        return False

    ip_token_bucket[ip] -= 1

    if ip_token_bucket[ip] == 0:
        timer = threading.Timer(60, reset_rate_limit_ip, [ip])
        timer.start()

    return True


app.register_blueprint(apiv1)
