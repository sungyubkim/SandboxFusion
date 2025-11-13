"""
Simple test script for SandboxFusion Router

Usage:
    # Start router first in another terminal:
    # uv run uvicorn router:app --host 0.0.0.0 --port 8000

    # Then run this test:
    python test_router.py
"""

import asyncio
import aiohttp


async def test_run_code():
    """Test /run_code endpoint with a simple Python program."""

    request = {
        "code": "print('Hello from SandboxFusion!')\nprint(2 + 2)",
        "language": "python",
        "run_timeout": 10
    }

    async with aiohttp.ClientSession() as session:
        print("Sending code execution request to router...")

        async with session.post(
            "http://localhost:8000/run_code",
            json=request
        ) as resp:
            print(f"Status: {resp.status}")

            if resp.status == 200:
                result = await resp.json()

                print("\n=== Execution Result ===")
                print(f"Status: {result['run']['status']}")
                print(f"Stdout: {result['run']['stdout']}")
                print(f"Stderr: {result['run']['stderr']}")
                print(f"Exit code: {result['run']['exit_code']}")

                if "router_metadata" in result:
                    print(f"\n=== Router Metadata ===")
                    print(f"Worker: {result['router_metadata']['worker_url']}")
                    print(f"Attempt: {result['router_metadata']['attempt']}")
            else:
                print(f"Error: {await resp.text()}")


async def test_health():
    """Test router health endpoint."""
    async with aiohttp.ClientSession() as session:
        async with session.get("http://localhost:8000/health") as resp:
            result = await resp.json()
            print("\n=== Router Health ===")
            print(f"Status: {result['status']}")
            print(f"Healthy workers: {result['healthy_workers']}/{result['total_workers']}")


async def test_root():
    """Test router root endpoint."""
    async with aiohttp.ClientSession() as session:
        async with session.get("http://localhost:8000/") as resp:
            result = await resp.json()
            print("\n=== Router Status ===")
            print(f"Service: {result['service']}")
            print(f"Version: {result['version']}")
            print("\nWorkers:")
            for worker in result['workers']:
                status = "✓" if worker['healthy'] else "✗"
                print(f"  {status} {worker['url']}")


async def main():
    try:
        await test_root()
        await test_health()
        await test_run_code()
    except aiohttp.ClientConnectorError:
        print("Error: Could not connect to router at http://localhost:8000")
        print("Make sure the router is running:")
        print("  uv run uvicorn router:app --host 0.0.0.0 --port 8000")
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    asyncio.run(main())
