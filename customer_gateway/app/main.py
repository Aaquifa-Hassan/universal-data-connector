"""
Customer Data API Gateway — Main Entry Point

This FastAPI application is deployed on the customer's side.
It owns:
  - Snowflake/Databricks credentials
  - All SQL queries
  - API key validation for incoming requests from your app
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import health, customers, orders

app = FastAPI(
    title="Customer Data API Gateway",
    description=(
        "Secure REST interface between Universal Data Connector and the "
        "customer's Snowflake / Databricks datalake. SQL and credentials "
        "never leave this service."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # Tighten to your app's domain in production
    allow_methods=["GET"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(health.router,    prefix="/api/v1")
app.include_router(customers.router, prefix="/api/v1")
app.include_router(orders.router,    prefix="/api/v1")
