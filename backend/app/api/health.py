# app/api/health.py

from fastapi import APIRouter


ROUTER = APIRouter()


@ROUTER.get(
    "/health"
)
async def health():

    return {

        "status":"healthy"

    }