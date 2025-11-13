"""
SandboxFusion Router - Standalone HTTP router for distributing code execution requests
across multiple SandboxFusion worker servers.

Usage:
    uv run uvicorn router:app --host 0.0.0.0 --port 8000
"""

import asyncio
import random
import time
from typing import Any, Dict, List, Optional

import aiohttp
import yaml
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# ============================================================================
# Configuration
# ============================================================================

class WorkerConfig(BaseModel):
    url: str
    healthy: bool = True
    last_check: float = 0.0
    last_error: str = ""


class RouterConfig(BaseModel):
    workers: List[Dict[str, str]]
    health_check_interval: int = 30
    timeout: int = 300
    routing_strategy: str = "round_robin"  # or "random"


def load_config(config_path: str = "config.yaml") -> RouterConfig:
    """Load router configuration from YAML file."""
    with open(config_path) as f:
        data = yaml.safe_load(f)
    return RouterConfig(**data)


# ============================================================================
# Worker Pool Manager
# ============================================================================

class WorkerPool:
    """Manages a pool of SandboxFusion worker servers with health checking."""

    def __init__(self, config: RouterConfig):
        self.config = config
        self.workers = [WorkerConfig(url=w["url"]) for w in config.workers]
        self.current_index = 0
        self.lock = asyncio.Lock()

    async def health_check(self, worker: WorkerConfig) -> bool:
        """Check if a worker is healthy by pinging its /v1/ping endpoint."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{worker.url}/v1/ping",
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as resp:
                    if resp.status == 200:
                        text = await resp.text()
                        text_stripped = text.strip()
                        if text_stripped == "pong":
                            worker.last_error = ""
                            print(f"✓ Worker {worker.url} is healthy")
                            return True
                        else:
                            worker.last_error = f"Unexpected response: {repr(text_stripped)}"
                            print(f"✗ Worker {worker.url} returned unexpected text: {repr(text_stripped)}")
                            return False
                    else:
                        worker.last_error = f"HTTP {resp.status}"
                        print(f"✗ Worker {worker.url} returned status {resp.status}")
                        return False
        except asyncio.TimeoutError:
            worker.last_error = "Connection timeout (5s)"
            print(f"✗ Worker {worker.url} timed out")
            return False
        except aiohttp.ClientConnectorError as e:
            worker.last_error = f"Connection failed: {str(e)}"
            print(f"✗ Worker {worker.url} connection error: {e}")
            return False
        except Exception as e:
            worker.last_error = f"Error: {str(e)}"
            print(f"✗ Worker {worker.url} error: {e}")
            return False

    async def update_health_status(self):
        """Periodically update health status of all workers."""
        while True:
            for worker in self.workers:
                now = time.time()
                if now - worker.last_check > self.config.health_check_interval:
                    worker.healthy = await self.health_check(worker)
                    worker.last_check = now
            await asyncio.sleep(10)

    async def get_worker(self) -> Optional[WorkerConfig]:
        """Get next healthy worker based on routing strategy."""
        healthy_workers = [w for w in self.workers if w.healthy]

        if not healthy_workers:
            # Force re-check all workers if none are healthy
            for worker in self.workers:
                worker.healthy = await self.health_check(worker)
            healthy_workers = [w for w in self.workers if w.healthy]

        if not healthy_workers:
            return None

        if self.config.routing_strategy == "random":
            return random.choice(healthy_workers)
        else:  # round_robin
            async with self.lock:
                # Find next healthy worker in round-robin order
                start_index = self.current_index
                for _ in range(len(self.workers)):
                    worker = self.workers[self.current_index]
                    self.current_index = (self.current_index + 1) % len(self.workers)
                    if worker.healthy:
                        return worker
                # If we've cycled through all and none are healthy
                return None


# ============================================================================
# FastAPI Application
# ============================================================================

app = FastAPI(
    title="SandboxFusion Router",
    description="HTTP router for distributing code execution requests across multiple SandboxFusion workers",
    version="1.0.0"
)

# Global worker pool (initialized on startup)
worker_pool: Optional[WorkerPool] = None


@app.on_event("startup")
async def startup_event():
    """Initialize worker pool and start health checking."""
    global worker_pool
    config = load_config()
    worker_pool = WorkerPool(config)

    print(f"Router started with {len(worker_pool.workers)} workers:")
    for w in worker_pool.workers:
        print(f"  - {w.url}")

    # Perform initial health check on all workers
    print("\nPerforming initial health checks...")
    for worker in worker_pool.workers:
        await worker_pool.health_check(worker)

    healthy_count = sum(1 for w in worker_pool.workers if w.healthy)
    print(f"\nInitial health check complete: {healthy_count}/{len(worker_pool.workers)} workers healthy")

    # Start background health check task
    asyncio.create_task(worker_pool.update_health_status())


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "service": "SandboxFusion Router",
        "version": "1.0.0",
        "workers": [
            {
                "url": w.url,
                "healthy": w.healthy,
                "last_check": w.last_check,
                "last_error": w.last_error
            }
            for w in worker_pool.workers
        ]
    }


@app.get("/health")
async def health():
    """Health check endpoint for the router itself."""
    healthy_count = sum(1 for w in worker_pool.workers if w.healthy)
    return {
        "status": "healthy" if healthy_count > 0 else "unhealthy",
        "total_workers": len(worker_pool.workers),
        "healthy_workers": healthy_count
    }


@app.post("/run_code")
async def run_code(request: Dict[str, Any]) -> Dict[str, Any]:
    """
    Forward code execution request to a healthy worker.

    Accepts the same request format as SandboxFusion's /run_code endpoint.
    """
    max_retries = min(3, len(worker_pool.workers))

    for attempt in range(max_retries):
        worker = await worker_pool.get_worker()

        if worker is None:
            raise HTTPException(
                status_code=503,
                detail="No healthy workers available"
            )

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{worker.url}/run_code",
                    json=request,
                    timeout=aiohttp.ClientTimeout(total=worker_pool.config.timeout)
                ) as resp:
                    if resp.status == 200:
                        result = await resp.json()
                        # Add router metadata
                        result["router_metadata"] = {
                            "worker_url": worker.url,
                            "attempt": attempt + 1
                        }
                        return result
                    else:
                        error_text = await resp.text()
                        print(f"Worker {worker.url} returned {resp.status}: {error_text}")
                        # Mark worker as unhealthy and retry
                        worker.healthy = False
                        continue

        except asyncio.TimeoutError:
            print(f"Worker {worker.url} timed out")
            worker.healthy = False
            continue

        except Exception as e:
            print(f"Worker {worker.url} error: {e}")
            worker.healthy = False
            continue

    raise HTTPException(
        status_code=503,
        detail=f"All workers failed after {max_retries} attempts"
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
