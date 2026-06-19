#!/usr/bin/env python3
"""
supabase_client.py — Shared Supabase client for the aionAI pipeline.

Usage:
    from lib.supabase_client import get_supabase, create_pipeline_run

    supabase = get_supabase()
    run_id = create_pipeline_run(supabase, run_date="2026-06-19")
"""

import os
import json
from datetime import date
from typing import Optional
from supabase import create_client, Client

# Singleton
_client: Optional[Client] = None


def get_supabase() -> Client:
    """Get or create the Supabase client singleton."""
    global _client
    if _client is None:
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")

        # Fallback: read from .env file
        if not url or not key:
            env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
            if os.path.exists(env_path):
                with open(env_path) as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("SUPABASE_URL="):
                            url = line.split("=", 1)[1]
                        elif line.startswith("SUPABASE_SERVICE_ROLE_KEY="):
                            key = line.split("=", 1)[1]

        if not url or not key:
            raise ValueError(
                "Supabase credentials not found. "
                "Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY env vars, "
                "or create a .env file in the project root."
            )

        _client = create_client(url, key)
    return _client


def create_pipeline_run(supabase: Client, run_date: Optional[str] = None,
                        seeds_used: int = 0, status: str = "running") -> str:
    """Create a new pipeline run entry and return its ID."""
    if run_date is None:
        run_date = date.today().isoformat()

    data = {
        "run_date": run_date,
        "status": status,
        "seeds_used": seeds_used,
    }
    result = supabase.table("pipeline_runs").insert(data).execute()
    return result.data[0]["id"]


def complete_pipeline_run(supabase: Client, run_id: str, status: str = "complete"):
    """Mark a pipeline run as complete."""
    supabase.table("pipeline_runs").update({"status": status}).eq("id", run_id).execute()


def upsert_status(supabase: Client, run_id: str, summary: str, full_snapshot: dict):
    """Insert or update the status snapshot for a run."""
    data = {
        "run_id": run_id,
        "summary": summary,
        "full_snapshot": full_snapshot,
    }
    # Check if exists
    existing = supabase.table("status_snapshots").select("id").eq("run_id", run_id).execute()
    if existing.data:
        supabase.table("status_snapshots").update(data).eq("run_id", run_id).execute()
    else:
        supabase.table("status_snapshots").insert(data).execute()


def load_json(path: str) -> dict:
    """Load a JSON file (helper for migration)."""
    with open(path) as f:
        return json.load(f)
