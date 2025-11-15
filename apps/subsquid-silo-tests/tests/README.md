# Pytest Tests for Subsquid Silo

Comprehensive test suite for all services and components.

## Test Coverage

### test_poller.py (180 LOC)
Tests for Gamma API Poller service
- **TestPollerParsing:** Market parsing from Gamma API
  - Single/multiple market parsing
  - Market status classification (ACTIVE/CLOSED)
  - Mid-price calculation from outcome prices
  - Handling missing prices
- **TestPollerErrorHandling:** Error handling
  - Malformed market data
  - Empty/None data
- **TestPollerBackoff:** Exponential backoff logic
  - Initial/max backoff values
  - Error count tracking
- **TestPollerMetrics:** Metrics collection
  - Poll count, market count, upsert count

### test_webhook.py (240 LOC)
Tests for FastAPI Webhook Worker
- **TestWebhookHealthCheck:** Health endpoint
  - Returns 200 status
  - Includes metrics
- **TestWebhookEventReceival:** Event reception
  - Valid event processing
  - Counter increments
  - Missing field validation
  - Complex JSONB payloads
- **TestWebhookErrorHandling:** Error scenarios
  - Missing market_id / event
  - Invalid JSON
  - Error counter increments
- **TestWebhookMetrics:** Metrics calculation
  - Success rate calculation
  - Event tracking
- **TestWebhookModel:** Pydantic model validation

### test_isolation.py (200 LOC)
Tests for feature flag and isolation
- **TestFeatureFlagValidation:** Feature flag protection
  - Flag validation
  - Raises without flag
- **TestTableIsolation:** Table name prefixes
  - All tables prefixed with `subsquid_`
  - Expected table names
- **TestServiceIsolation:** Service isolation
  - Services only access subsquid_* tables
- **TestConfigIsolation:** Configuration
  - Environment variables set
  - DATABASE_URL, REDIS_URL, EXPERIMENTAL_SUBSQUID
- **TestNoProductionAccess:** Safety checks
  - No production table access
- **TestEnvironmentVariables:** Env var validation

### conftest.py (150 LOC)
Pytest configuration
- Event loop fixture for async tests
- Mock database client fixture
- Mock Redis client fixture
- Session setup and metrics reset
- Test hooks and logging

## Running Tests

### Run All Tests
```bash
pytest
```

### Run Specific Test File
```bash
pytest tests/test_poller.py
pytest tests/test_webhook.py
pytest tests/test_isolation.py
```

### Run Specific Test Class
```bash
pytest tests/test_poller.py::TestPollerParsing
pytest tests/test_webhook.py::TestWebhookErrorHandling
```

### Run Specific Test
```bash
pytest tests/test_poller.py::TestPollerParsing::test_parse_single_market
pytest tests/test_webhook.py::TestWebhookEventReceival::test_receive_valid_event
```

### Run with Verbose Output
```bash
pytest -v
pytest -vv  # Even more verbose
```

### Run with Coverage
```bash
pytest --cov=src
pytest --cov=src --cov-report=html
```

### Run in Parallel (faster)
```bash
pytest -n auto  # Requires pytest-xdist
```

## Test Setup

### Prerequisites
```bash
pip install -r requirements.txt
pip install pytest pytest-asyncio pytest-cov pytest-xdist
```

### Environment Variables
Tests automatically set:
- `EXPERIMENTAL_SUBSQUID=true`
- `DATABASE_URL=postgresql://test:test@localhost:5432/test_subsquid`
- `REDIS_URL=redis://localhost:6379/1`

Override with:
```bash
export DATABASE_URL=postgresql://...
pytest
```

## Test Categories

### Unit Tests
- Parsing logic (poller, streamer)
- Model validation (WebhookEvent)
- Metrics calculation
- Configuration loading

### Integration Tests
- FastAPI endpoint behavior
- Database operations (mocked)
- Redis operations (mocked)

### Safety Tests
- Feature flag enforcement
- Table name isolation
- No production access

## Mocking Strategy

### Database Client
```python
mock_db_client.upsert_markets_poll = AsyncMock(return_value=10)
mock_db_client.insert_webhook_event = AsyncMock(return_value=1)
```

### Redis Client
```python
mock_redis_client.publish = AsyncMock(return_value=1)
mock_redis_client.info = AsyncMock(return_value={...})
```

### HTTP Requests
Tests for webhook use FastAPI TestClient - no actual HTTP calls

### WebSocket
Streamer tests mock websocket connections (not yet implemented)

## CI/CD Integration

### GitHub Actions Example
```yaml
name: Tests
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - uses: actions/setup-python@v2
        with:
          python-version: 3.10
      - run: pip install -r requirements.txt pytest pytest-asyncio
      - run: pytest
```

## Coverage Targets

Current coverage targets:
- Poller: 90%+
- Streamer: 80%+
- Webhook: 95%+
- Isolation: 100%

Run to check:
```bash
pytest --cov=src --cov-report=term-missing
```

## Debugging

### Print Debug Info
```bash
pytest -s  # Don't capture output
```

### Stop on First Failure
```bash
pytest -x
```

### Enter Debugger on Failure
```bash
pytest --pdb
```

### Show Slowest Tests
```bash
pytest --durations=10
```

## Known Limitations

1. **Database Tests:** Use mocks, not real PostgreSQL
   - For integration tests, run services locally
2. **WebSocket Tests:** Mock only, not real CLOB WS
3. **Redis Tests:** Mock only, not real Redis
4. **Rate Limiting:** Tests don't validate backoff timing

## Future Enhancements

- [ ] Real database integration tests (testcontainers)
- [ ] Real WebSocket mock (websocket-client)
- [ ] End-to-end tests with docker-compose
- [ ] Performance benchmarks
- [ ] Load tests for webhook concurrency
