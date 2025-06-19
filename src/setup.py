import os

from fastapi import FastAPI
from pancaik import init


async def setup(app: FastAPI = None):
    config = {
        "db_connection": os.getenv(
            "MONGO_CONNECTION", "mongodb://localhost:27017/demether"
        ),
    }
    await init(
        app=app,
        config=config,
    )
