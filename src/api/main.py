
import os
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import duckdb
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from src.agent.agent import SQLAgent
from src.agent.models import GeminiModel
from src.agent.schema import load_schema


load_dotenv()

ROOT_DIR = Path(__file__).resolve().parents[2]
DATABASE_PATH = ROOT_DIR / "db" / "food_delivery.duckdb"
SCHEMA_PATH = ROOT_DIR / "datasets" / "text2sql" / "schema.txt"

app = FastAPI(
    title="FoodSQL-Agent API",
    description="Food delivery analytics and Gemini-powered Text-to-SQL API",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class AgentQuery(BaseModel):
    question: str = Field(min_length=3, max_length=1000)


def get_connection():
    return duckdb.connect(str(DATABASE_PATH), read_only=True)


def serialize_value(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


_agent = None


def get_agent():
    global _agent

    if _agent is None:
        if not SCHEMA_PATH.exists():
            raise RuntimeError("Database schema file not found.")

        schema = load_schema(SCHEMA_PATH)
        model_name = os.getenv(
            "FOODSQL_GEMINI_MODEL",
            "gemini-3.5-flash-lite",
        )

        model = GeminiModel(model=model_name, rpm=8)

        _agent = {
            "model": model,
            "schema": schema,
        }

    return _agent


@app.get("/")
def home():
    return {
        "message": "Welcome to FoodSQL-Agent API",
        "status": "running",
        "docs": "/docs",
    }


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "service": "FoodSQL-Agent API",
    }


@app.get("/analytics/summary")
def analytics_summary():
    connection = None

    try:
        connection = get_connection()

        total_orders = connection.execute(
            "SELECT COUNT(*) FROM streaming_orders"
        ).fetchone()[0]

        total_revenue = connection.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM streaming_orders"
        ).fetchone()[0]

        average_order_value = connection.execute(
            "SELECT COALESCE(AVG(amount), 0) FROM streaming_orders"
        ).fetchone()[0]

        latest_order_time = connection.execute(
            "SELECT MAX(event_time) FROM streaming_orders"
        ).fetchone()[0]

        status_summary = connection.execute("""
            SELECT status, COUNT(*)
            FROM streaming_orders
            GROUP BY status
            ORDER BY status
        """).fetchall()

        return {
            "total_orders": total_orders,
            "total_revenue": float(total_revenue),
            "average_order_value": float(average_order_value),
            "latest_order_time": serialize_value(latest_order_time),
            "order_status": [
                {"status": status, "count": count}
                for status, count in status_summary
            ],
        }

    except Exception as error:
        print(f"Analytics error: {error}")
        raise HTTPException(
            status_code=500,
            detail="Unable to retrieve analytics summary.",
        ) from error

    finally:
        if connection is not None:
            connection.close()


@app.get("/analytics/status")
def analytics_status():
    connection = None

    try:
        connection = get_connection()

        results = connection.execute("""
            SELECT status, COUNT(*) AS total
            FROM streaming_orders
            GROUP BY status
            ORDER BY status
        """).fetchall()

        return {
            "statuses": [
                {"status": status, "total": count}
                for status, count in results
            ]
        }

    except Exception as error:
        print(f"Status analytics error: {error}")
        raise HTTPException(
            status_code=500,
            detail="Unable to retrieve order status analytics.",
        ) from error

    finally:
        if connection is not None:
            connection.close()


@app.post("/agent/query")
def agent_query(request: AgentQuery):
    connection = None

    try:
        agent_config = get_agent()
        connection = get_connection()

        agent = SQLAgent(
            model=agent_config["model"],
            con=connection,
            schema=agent_config["schema"],
            use_loop=True,
            max_repairs=3,
            max_rows=100,
        )

        result = agent.answer(request.question)
        result["latency_ms"] = round(result.get("latency_s", 0) * 1000, 2)
        return {
            "question": request.question,
            "model": agent_config["model"].name,
            **result,
        }

    except Exception as error:
        print(f"Agent query error: {error}")
        raise HTTPException(
            status_code=500,
            detail=f"Agent query failed: {str(error)[:300]}",
        ) from error

    finally:
        if connection is not None:
            connection.close()
