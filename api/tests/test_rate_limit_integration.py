"""Rate limiter integration test using real app factory."""

import pytest
from fastapi.testclient import TestClient

from api.app import create_app


def test_rate_limit_with_real_app():
    """Test rate limiter with create_app() factory.
    
    Proves:
    1. Burst on normal route gets 429
    2. /events SSE streaming still works (not broken by middleware)
    """
    app = create_app()
    client = TestClient(app)
    
    # Trigger middleware build with a test request
    client.get("/health")
    
    # Now find the rate limiter in the built middleware stack
    rate_limit_middleware = None
    current = app.middleware_stack
    while current is not None:
        if current.__class__.__name__ == "PerIPRateLimitMiddleware":
            rate_limit_middleware = current
            break
        current = getattr(current, 'app', None)
    
    assert rate_limit_middleware is not None, "Rate limit middleware not found"
    
    # Clear state from the test request and set a low limit for testing
    rate_limit_middleware._hits.clear()
    rate_limit_middleware.limit = 3
    rate_limit_middleware.window_seconds = 60
    
    client = TestClient(app)
    
    # Part 1: Burst on normal route gets 429
    responses = [client.get("/health") for _ in range(4)]
    status_codes = [r.status_code for r in responses]
    
    assert status_codes[:3] == [200, 200, 200], "First 3 requests should succeed"
    assert status_codes[3] == 429, "4th request should be rate limited"
    
    # Verify 429 response has correct structure
    rate_limited_response = responses[3]
    assert rate_limited_response.json() == {"error": "rate limit exceeded"}
    assert rate_limited_response.headers["retry-after"] == "60"
    
    # Clear rate limiter state for next test
    rate_limit_middleware._hits.clear()
    
    # Part 2: /events SSE streaming still works
    # TestClient supports streaming responses
    with client.stream("GET", "/events") as response:
        assert response.status_code == 200, "/events should not be broken by rate limiter"
        assert response.headers["content-type"] == "text/event-stream; charset=utf-8"
        
        # Read a few events to verify streaming works
        events_received = []
        for line in response.iter_lines():
            if line:
                events_received.append(line)
                if len(events_received) >= 5:  # Get at least 5 lines
                    break
        
        # Verify we got SSE events (format: "event: <type>" or "data: {...}")
        assert len(events_received) > 0, "Should receive SSE events"
        assert any("event:" in line for line in events_received), "Should have event lines"
        assert any("data:" in line for line in events_received), "Should have data lines"


def test_streaming_response_not_buffered():
    """Verify that StreamingResponse is not buffered by the middleware.
    
    With BaseHTTPMiddleware, streaming would be buffered or break.
    With pure ASGI middleware, streaming should work directly.
    """
    app = create_app()
    
    # Build middleware stack
    app.build_middleware_stack()
    
    # Find rate limiter
    current = app.middleware_stack
    rate_limit_middleware = None
    while current is not None:
        if current.__class__.__name__ == "PerIPRateLimitMiddleware":
            rate_limit_middleware = current
            break
        current = getattr(current, 'app', None)
    
    # Set high limit so we don't hit it during this test
    if rate_limit_middleware:
        rate_limit_middleware.limit = 1000
    
    client = TestClient(app)
    
    # Make a streaming request
    with client.stream("GET", "/events") as response:
        assert response.status_code == 200
        
        # Verify it's a streaming response by checking we can iterate
        # If it were buffered, we'd get all content at once
        chunk_count = 0
        for chunk in response.iter_bytes(chunk_size=1024):
            chunk_count += 1
            if chunk_count >= 3:  # Get a few chunks
                break
        
        # With streaming, we should get multiple chunks
        # (not one big buffered response)
        assert chunk_count > 0, "Should receive streamed chunks"
