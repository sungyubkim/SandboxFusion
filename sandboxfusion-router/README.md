# SandboxFusion Router

A standalone HTTP router for distributing code execution requests across multiple SandboxFusion worker servers. This enables horizontal scaling and high concurrency for LLM-generated code execution.

## Features

- ✅ **Stateless routing** - No session affinity required
- ✅ **Automatic health checking** - Unhealthy workers are automatically excluded
- ✅ **Retry logic** - Failed requests are automatically retried on other workers
- ✅ **Multiple routing strategies** - Round-robin or random
- ✅ **Zero dependencies on SandboxFusion** - Completely standalone
- ✅ **Minimal footprint** - Only 4 dependencies (FastAPI, aiohttp, uvicorn, PyYAML)

## Architecture

```
Client Request
    ↓
Router Server (this project)
    ↓ (Round-robin / Random routing)
Worker 1, 2, 3, ... (SandboxFusion servers via singularity exec)
```

## Installation

```bash
# Clone or copy this directory
cd sandboxfusion-router

# Install dependencies with uv
uv venv
source .venv/bin/activate
uv sync
```

## Configuration

Edit `config.yaml` to specify your worker servers:

```yaml
workers:
  - url: http://server1.example.com:8080
  - url: http://server2.example.com:8080
  - url: http://server3.example.com:8080

health_check_interval: 30  # Health check every 30 seconds
timeout: 300                # Request timeout in seconds
routing_strategy: round_robin  # or "random"
```

## Usage

### Start the Router

```bash
# Development mode
uv run uvicorn router:app --host 0.0.0.0 --port 8000

# Production mode with multiple workers
uv run uvicorn router:app --host 0.0.0.0 --port 8000 --workers 4
```

### Start Worker Servers

On each worker server, run SandboxFusion using Singularity:

```bash
# Start SandboxFusion worker
singularity exec \
  --bind /tmp:/tmp \
  sandboxfusion.sif \
  python -m sandbox.server.server

# Or with custom host/port
singularity exec \
  --bind /tmp:/tmp \
  --env HOST=0.0.0.0 \
  --env PORT=8080 \
  sandboxfusion.sif \
  python -m sandbox.server.server
```

**Note**: Ensure the SandboxFusion server is configured with `isolation: none` and `dataset` section is properly set (no database required if only using `/run_code`).

### Send Requests

The router exposes the same `/run_code` API as SandboxFusion:

```bash
curl -X POST http://localhost:8000/run_code \
  -H "Content-Type: application/json" \
  -d '{
    "code": "print(\"Hello from worker!\")",
    "language": "python"
  }'
```

Response includes worker metadata:

```json
{
  "compile": {...},
  "run": {...},
  "router_metadata": {
    "worker_url": "http://server1.example.com:8080",
    "attempt": 1
  }
}
```

## API Endpoints

### `POST /run_code`

Forward code execution request to a healthy worker. Accepts the same request format as SandboxFusion's `/run_code` endpoint.

**Request body**: See [SandboxFusion API documentation](https://bytedance.github.io/SandboxFusion/)

**Response**: Same as SandboxFusion's response, with additional `router_metadata` field.

### `GET /`

Get router status and worker health information.

**Response**:
```json
{
  "service": "SandboxFusion Router",
  "version": "1.0.0",
  "workers": [
    {"url": "http://server1:8080", "healthy": true},
    {"url": "http://server2:8080", "healthy": false}
  ]
}
```

### `GET /health`

Health check endpoint for the router itself.

**Response**:
```json
{
  "status": "healthy",
  "total_workers": 3,
  "healthy_workers": 2
}
```

## Deployment Recommendations

### 1. Single Router + Multiple Workers

```
Router (1 instance) → Workers (N instances)
```

Simple setup, router is a single point of failure but lightweight and rarely fails.

### 2. Multiple Routers with Load Balancer

```
Load Balancer → Routers (M instances) → Workers (N instances)
```

For high availability, deploy multiple router instances behind nginx/HAProxy.

### 3. Kubernetes Deployment

```yaml
# router-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: sandboxfusion-router
spec:
  replicas: 2
  template:
    spec:
      containers:
      - name: router
        image: your-registry/sandboxfusion-router:latest
        ports:
        - containerPort: 8000
        volumeMounts:
        - name: config
          mountPath: /app/config.yaml
          subPath: config.yaml
      volumes:
      - name: config
        configMap:
          name: router-config
```

## Performance

- **Latency overhead**: <10ms per request (HTTP forwarding only)
- **Throughput**: Limited by network bandwidth, typically >1000 req/s
- **Scalability**: Horizontal scaling by adding more workers in `config.yaml`

## Monitoring

The router logs all worker failures and health check results to stdout:

```
Worker http://server1:8080 timed out
Worker http://server2:8080 returned 500: Internal Server Error
Router started with 3 workers:
  - http://server1:8080
  - http://server2:8080
  - http://server3:8080
```

Integrate with your logging infrastructure (e.g., ELK stack, CloudWatch) for production monitoring.

## Troubleshooting

### No healthy workers available

**Symptom**: `503 No healthy workers available`

**Solutions**:
1. Check worker servers are running: `curl http://server1:8080/v1/ping`
2. Verify network connectivity from router to workers
3. Check worker logs for errors

### Requests timing out

**Symptom**: `503 All workers failed after N attempts`

**Solutions**:
1. Increase `timeout` in `config.yaml`
2. Check worker server load (CPU/memory)
3. Reduce `max_concurrency` in worker's SandboxFusion config

### Workers marked unhealthy incorrectly

**Symptom**: Workers show `healthy: false` but are actually working

**Solutions**:
1. Increase `health_check_interval` in `config.yaml`
2. Check network latency between router and workers
3. Verify `/v1/ping` endpoint returns "pong" correctly

## License

This router is designed to work with SandboxFusion (Apache 2.0 License) but is completely independent and can be used/modified freely.

## Contributing

This is a minimal router implementation. Suggested improvements:

- [ ] Weighted routing (send more traffic to powerful workers)
- [ ] Worker statistics (track request counts, latencies)
- [ ] Dynamic worker registration (workers register themselves)
- [ ] Circuit breaker pattern (temporarily disable failing workers)
- [ ] Prometheus metrics export
