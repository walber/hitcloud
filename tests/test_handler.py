"""
Unit tests and property-based tests for lambda/handler.py
==========================================================

Unit test coverage (task 3.2 — Requirements 11.1):
  - GET /count returns {"count": 0} when no item exists in DynamoDB
  - GET /count does not call UpdateItem (read isolation)
  - POST /hit calls UpdateItem with the atomic expression and returns the count
  - Concurrent POST /hit via mocked atomic semantics does not lose increments
  - DynamoDB ClientError returns HTTP 503
  - Unknown method/path returns HTTP 405

Property-based tests (task 3.3 — Requirements 11.2):
  Property 1:  CORS headers present on every response path       — Validates: Requirements 4.2
  Property 2:  Cache-Control: no-store on every response         — Validates: Requirements 6.5
  Property 3:  POST /hit returns DynamoDB count for any N        — Validates: Requirements 3.4
  Property 4:  GET /count returns 0 when item absent             — Validates: Requirements 3.6, 5.4
  Property 5:  GET /count returns stored count for any N         — Validates: Requirements 3.6
  Property 6:  GET /count never calls UpdateItem                 — Validates: Requirements 3.7
  Property 7:  Counter item key is always {"id": {"S": "hits"}}  — Validates: Requirements 3.4
  Property 8:  DynamoDB throttle errors produce HTTP 503         — Validates: Requirements 3.8
  Property 9:  Any unexpected exception produces HTTP 503        — Validates: Requirements 3.8
  Property 10: Unknown HTTP methods produce HTTP 405             — Validates: Requirements 3.9
"""

import importlib.util
import json
import os
import pathlib
from decimal import Decimal
from unittest.mock import MagicMock, call, patch

import pytest
from botocore.exceptions import ClientError
from hypothesis import given, settings
from hypothesis import strategies as st

# ---------------------------------------------------------------------------
# Module-level bootstrap
# ---------------------------------------------------------------------------
# handler.py executes boto3.resource("dynamodb") at import time, which would
# require live AWS credentials. We intercept that call with a MagicMock so
# the module loads cleanly in any environment.

os.environ.setdefault("TABLE_NAME", "test-table")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

_HANDLER_PATH = pathlib.Path(__file__).parent.parent / "lambda" / "handler.py"

_mock_boto3_resource = MagicMock()

with patch("boto3.resource", _mock_boto3_resource):
    _spec = importlib.util.spec_from_file_location("handler_module", _HANDLER_PATH)
    handler_module = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(handler_module)

handler = handler_module.handler

# ---------------------------------------------------------------------------
# Shared test helpers
# ---------------------------------------------------------------------------

def _client_error(code: str = "InternalError") -> ClientError:
    """Build a botocore ClientError for a given error code."""
    return ClientError(
        error_response={"Error": {"Code": code, "Message": "test error"}},
        operation_name="UpdateItem",
    )


def _make_resource_mock(item=None, get_item_raises=None):
    """
    Return a mock boto3 DynamoDB resource.

    - item: the Item dict returned by get_item (None → item absent)
    - get_item_raises: an exception to raise instead of returning
    """
    mock_table = MagicMock()
    if get_item_raises is not None:
        mock_table.get_item.side_effect = get_item_raises
    else:
        mock_table.get_item.return_value = {"Item": item} if item is not None else {}
    mock_resource = MagicMock()
    mock_resource.Table.return_value = mock_table
    return mock_resource, mock_table


def _make_client_mock(count: int | None = None, update_raises=None):
    """
    Return a mock boto3 DynamoDB low-level client for POST /hit tests.

    - count: the integer count value in the UpdateItem response Attributes
    - update_raises: an exception to raise instead of returning
    """
    mock_client = MagicMock()
    if update_raises is not None:
        mock_client.update_item.side_effect = update_raises
    else:
        mock_client.update_item.return_value = {
            "Attributes": {"count": {"N": str(count)}}
        }
    return mock_client


# ---------------------------------------------------------------------------
# Unit Tests — GET /count (Requirements 11.1, 3.6)
# ---------------------------------------------------------------------------

class TestGetCount:
    """Unit tests for the GET /count route."""

    GET_EVENT = {"httpMethod": "GET", "path": "/count"}

    def test_returns_zero_when_item_absent(self):
        """GET /count → {"count": 0} when DynamoDB returns no item."""
        resource_mock, _ = _make_resource_mock(item=None)
        with patch.object(handler_module, "dynamodb", resource_mock):
            response = handler(self.GET_EVENT, None)

        assert response["statusCode"] == 200
        assert json.loads(response["body"]) == {"count": 0}

    def test_returns_stored_count(self):
        """GET /count → {"count": N} when item exists with count=N."""
        resource_mock, _ = _make_resource_mock(item={"id": "hits", "count": Decimal("42")})
        with patch.object(handler_module, "dynamodb", resource_mock):
            response = handler(self.GET_EVENT, None)

        assert response["statusCode"] == 200
        assert json.loads(response["body"]) == {"count": 42}

    def test_does_not_call_update_item(self):
        """GET /count must never call UpdateItem — read isolation requirement."""
        resource_mock, mock_table = _make_resource_mock(item={"id": "hits", "count": Decimal("7")})
        with patch.object(handler_module, "dynamodb", resource_mock):
            handler(self.GET_EVENT, None)

        mock_table.update_item.assert_not_called()

    def test_uses_consistent_read(self):
        """GET /count must pass ConsistentRead=True to GetItem."""
        resource_mock, mock_table = _make_resource_mock(item=None)
        with patch.object(handler_module, "dynamodb", resource_mock):
            handler(self.GET_EVENT, None)

        call_kwargs = mock_table.get_item.call_args.kwargs
        assert call_kwargs.get("ConsistentRead") is True

    def test_uses_correct_key(self):
        """GET /count must query the key {"id": "hits"}."""
        resource_mock, mock_table = _make_resource_mock(item=None)
        with patch.object(handler_module, "dynamodb", resource_mock):
            handler(self.GET_EVENT, None)

        call_kwargs = mock_table.get_item.call_args.kwargs
        assert call_kwargs.get("Key") == {"id": "hits"}

    def test_client_error_returns_503(self):
        """GET /count → 503 when DynamoDB raises a ClientError."""
        resource_mock, _ = _make_resource_mock(get_item_raises=_client_error())
        with patch.object(handler_module, "dynamodb", resource_mock):
            response = handler(self.GET_EVENT, None)

        assert response["statusCode"] == 503
        assert json.loads(response["body"]) == {"error": "Service temporarily unavailable"}

    def test_generic_exception_returns_503(self):
        """GET /count → 503 when any unexpected exception is raised."""
        resource_mock, _ = _make_resource_mock(get_item_raises=RuntimeError("boom"))
        with patch.object(handler_module, "dynamodb", resource_mock):
            response = handler(self.GET_EVENT, None)

        assert response["statusCode"] == 503
        assert json.loads(response["body"]) == {"error": "Service temporarily unavailable"}


# ---------------------------------------------------------------------------
# Unit Tests — POST /hit (Requirements 11.1, 3.4, 3.5)
# ---------------------------------------------------------------------------

class TestPostHit:
    """Unit tests for the POST /hit route."""

    POST_EVENT = {"httpMethod": "POST", "path": "/hit"}

    def test_calls_update_item_with_atomic_expression(self):
        """POST /hit must call UpdateItem with the if_not_exists atomic expression."""
        mock_client = _make_client_mock(count=1)
        with patch("boto3.client", return_value=mock_client):
            handler(self.POST_EVENT, None)

        mock_client.update_item.assert_called_once()
        kwargs = mock_client.update_item.call_args.kwargs
        assert "if_not_exists" in kwargs["UpdateExpression"]
        assert ":zero" in kwargs["ExpressionAttributeValues"]
        assert ":one" in kwargs["ExpressionAttributeValues"]

    def test_returns_count_from_dynamodb(self):
        """POST /hit → {"count": N} with the value returned by UpdateItem."""
        mock_client = _make_client_mock(count=99)
        with patch("boto3.client", return_value=mock_client):
            response = handler(self.POST_EVENT, None)

        assert response["statusCode"] == 200
        assert json.loads(response["body"]) == {"count": 99}

    def test_uses_key_id_hits(self):
        """POST /hit must call UpdateItem with Key={"id": {"S": "hits"}}."""
        mock_client = _make_client_mock(count=1)
        with patch("boto3.client", return_value=mock_client):
            handler(self.POST_EVENT, None)

        kwargs = mock_client.update_item.call_args.kwargs
        assert kwargs["Key"] == {"id": {"S": "hits"}}

    def test_uses_return_values_all_new(self):
        """POST /hit must request ReturnValues=ALL_NEW from UpdateItem."""
        mock_client = _make_client_mock(count=1)
        with patch("boto3.client", return_value=mock_client):
            handler(self.POST_EVENT, None)

        kwargs = mock_client.update_item.call_args.kwargs
        assert kwargs.get("ReturnValues") == "ALL_NEW"

    def test_client_error_returns_503(self):
        """POST /hit → 503 on DynamoDB ClientError."""
        mock_client = _make_client_mock(update_raises=_client_error("ThrottlingException"))
        with patch("boto3.client", return_value=mock_client):
            response = handler(self.POST_EVENT, None)

        assert response["statusCode"] == 503
        assert json.loads(response["body"]) == {"error": "Service temporarily unavailable"}

    def test_generic_exception_returns_503(self):
        """POST /hit → 503 on any unexpected exception."""
        mock_client = _make_client_mock(update_raises=ValueError("unexpected"))
        with patch("boto3.client", return_value=mock_client):
            response = handler(self.POST_EVENT, None)

        assert response["statusCode"] == 503
        assert json.loads(response["body"]) == {"error": "Service temporarily unavailable"}

    def test_concurrent_increments_do_not_lose_counts(self):
        """
        Simulate N concurrent POST /hit calls via atomic counter semantics.

        Each call gets the count it deserves (sequential integers) because
        UpdateItem is atomic. We verify no increment is lost by checking the
        final count equals the number of calls, and each response contains a
        unique count value.
        """
        n = 20
        counts = list(range(1, n + 1))  # 1..N — what DynamoDB would return atomically
        call_index = [0]

        def _side_effect(**kwargs):
            idx = call_index[0]
            call_index[0] += 1
            return {"Attributes": {"count": {"N": str(counts[idx])}}}

        mock_client = MagicMock()
        mock_client.update_item.side_effect = _side_effect

        responses = []
        with patch("boto3.client", return_value=mock_client):
            for _ in range(n):
                resp = handler(self.POST_EVENT, None)
                responses.append(json.loads(resp["body"])["count"])

        # All N increments happened, each returning a distinct sequential value
        assert mock_client.update_item.call_count == n
        assert sorted(responses) == counts  # no count was lost or duplicated


# ---------------------------------------------------------------------------
# Unit Tests — Routing edge cases (Requirements 11.1, 3.9)
# ---------------------------------------------------------------------------

class TestRouting:
    """Unit tests for unrecognised methods and paths."""

    @pytest.mark.parametrize("method, path", [
        ("DELETE", "/hit"),
        ("PUT", "/count"),
        ("PATCH", "/hit"),
        ("GET", "/hit"),          # wrong path for GET
        ("POST", "/count"),       # wrong path for POST
        ("GET", "/unknown"),
        ("", ""),
    ])
    def test_unknown_method_or_path_returns_405(self, method, path):
        """Any unrecognised method/path combination → HTTP 405."""
        response = handler({"httpMethod": method, "path": path}, None)
        assert response["statusCode"] == 405
        assert json.loads(response["body"]) == {"error": "Method not allowed"}

    def test_options_returns_200(self):
        """OPTIONS (CORS preflight) → HTTP 200 with CORS headers."""
        response = handler({"httpMethod": "OPTIONS", "path": "/hit"}, None)
        assert response["statusCode"] == 200

    def test_options_has_cors_headers(self):
        """OPTIONS response must include Access-Control-Allow-Origin."""
        response = handler({"httpMethod": "OPTIONS", "path": "/hit"}, None)
        assert "Access-Control-Allow-Origin" in response["headers"]

    def test_missing_httpMethod_key_returns_405(self):
        """Event with no httpMethod key → 405 (defaults to empty string)."""
        response = handler({"path": "/hit"}, None)
        assert response["statusCode"] == 405

    def test_missing_path_key_returns_405(self):
        """Event with no path key → 405 (defaults to empty string)."""
        response = handler({"httpMethod": "POST"}, None)
        assert response["statusCode"] == 405


# ---------------------------------------------------------------------------
# Property 1: CORS headers present on every response path
# Validates: Requirements 4.2
# ---------------------------------------------------------------------------

class TestProperty1CorsHeadersAlwaysPresent:
    """CORS headers must appear in all responses regardless of route or outcome."""

    REQUIRED_CORS = {
        "Access-Control-Allow-Origin": os.environ.get("ALLOWED_ORIGIN", "*"),
        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    }

    def _assert_cors(self, response):
        headers = response.get("headers", {})
        for key, expected in self.REQUIRED_CORS.items():
            assert key in headers, f"Missing CORS header: {key}"
            assert headers[key] == expected, (
                f"Header {key!r}: got {headers[key]!r}, expected {expected!r}"
            )

    def test_cors_on_get_count_success(self):
        resource_mock, _ = _make_resource_mock(item={"id": "hits", "count": Decimal("1")})
        with patch.object(handler_module, "dynamodb", resource_mock):
            self._assert_cors(handler({"httpMethod": "GET", "path": "/count"}, None))

    def test_cors_on_get_count_absent(self):
        resource_mock, _ = _make_resource_mock(item=None)
        with patch.object(handler_module, "dynamodb", resource_mock):
            self._assert_cors(handler({"httpMethod": "GET", "path": "/count"}, None))

    def test_cors_on_get_count_error(self):
        resource_mock, _ = _make_resource_mock(get_item_raises=_client_error())
        with patch.object(handler_module, "dynamodb", resource_mock):
            self._assert_cors(handler({"httpMethod": "GET", "path": "/count"}, None))

    def test_cors_on_post_hit_success(self):
        mock_client = _make_client_mock(count=5)
        with patch("boto3.client", return_value=mock_client):
            self._assert_cors(handler({"httpMethod": "POST", "path": "/hit"}, None))

    def test_cors_on_post_hit_error(self):
        mock_client = _make_client_mock(update_raises=_client_error())
        with patch("boto3.client", return_value=mock_client):
            self._assert_cors(handler({"httpMethod": "POST", "path": "/hit"}, None))

    def test_cors_on_options(self):
        self._assert_cors(handler({"httpMethod": "OPTIONS", "path": "/hit"}, None))

    def test_cors_on_405(self):
        self._assert_cors(handler({"httpMethod": "DELETE", "path": "/hit"}, None))

    @given(n=st.integers(min_value=1, max_value=10_000_000))
    @settings(max_examples=50)
    def test_cors_on_any_get_count_value(self, n):
        resource_mock, _ = _make_resource_mock(
            item={"id": "hits", "count": Decimal(str(n))}
        )
        with patch.object(handler_module, "dynamodb", resource_mock):
            self._assert_cors(handler({"httpMethod": "GET", "path": "/count"}, None))

    @given(n=st.integers(min_value=1, max_value=10_000_000))
    @settings(max_examples=50)
    def test_cors_on_any_post_hit_value(self, n):
        mock_client = _make_client_mock(count=n)
        with patch("boto3.client", return_value=mock_client):
            self._assert_cors(handler({"httpMethod": "POST", "path": "/hit"}, None))


# ---------------------------------------------------------------------------
# Property 2: Cache-Control: no-store on every response
# Validates: Requirements 6.5
# ---------------------------------------------------------------------------

class TestProperty2CacheControlNoStore:
    """Cache-Control: no-store must appear in every response."""

    def _assert_no_store(self, response):
        cc = response.get("headers", {}).get("Cache-Control", "")
        assert "no-store" in cc, f"Cache-Control header missing 'no-store': {cc!r}"

    def test_no_store_on_get_count_success(self):
        resource_mock, _ = _make_resource_mock(item={"id": "hits", "count": Decimal("1")})
        with patch.object(handler_module, "dynamodb", resource_mock):
            self._assert_no_store(handler({"httpMethod": "GET", "path": "/count"}, None))

    def test_no_store_on_get_count_absent(self):
        resource_mock, _ = _make_resource_mock(item=None)
        with patch.object(handler_module, "dynamodb", resource_mock):
            self._assert_no_store(handler({"httpMethod": "GET", "path": "/count"}, None))

    def test_no_store_on_get_count_error(self):
        resource_mock, _ = _make_resource_mock(get_item_raises=_client_error())
        with patch.object(handler_module, "dynamodb", resource_mock):
            self._assert_no_store(handler({"httpMethod": "GET", "path": "/count"}, None))

    def test_no_store_on_post_hit_success(self):
        mock_client = _make_client_mock(count=3)
        with patch("boto3.client", return_value=mock_client):
            self._assert_no_store(handler({"httpMethod": "POST", "path": "/hit"}, None))

    def test_no_store_on_post_hit_error(self):
        mock_client = _make_client_mock(update_raises=_client_error())
        with patch("boto3.client", return_value=mock_client):
            self._assert_no_store(handler({"httpMethod": "POST", "path": "/hit"}, None))

    def test_no_store_on_options(self):
        self._assert_no_store(handler({"httpMethod": "OPTIONS", "path": "/hit"}, None))

    def test_no_store_on_405(self):
        self._assert_no_store(handler({"httpMethod": "DELETE", "path": "/hit"}, None))

    @given(n=st.integers(min_value=0, max_value=10_000_000))
    @settings(max_examples=50)
    def test_no_store_for_any_post_hit_count(self, n):
        mock_client = _make_client_mock(count=n)
        with patch("boto3.client", return_value=mock_client):
            self._assert_no_store(handler({"httpMethod": "POST", "path": "/hit"}, None))


# ---------------------------------------------------------------------------
# Property 3: POST /hit returns the count value from DynamoDB for any N
# Validates: Requirements 3.4
# ---------------------------------------------------------------------------

class TestProperty3PostHitReturnsCount:
    """POST /hit body must reflect exactly the count returned by DynamoDB."""

    @given(n=st.integers(min_value=1, max_value=10_000_000))
    @settings(max_examples=100)
    def test_status_200_and_count_equals_dynamodb_value(self, n):
        mock_client = _make_client_mock(count=n)
        with patch("boto3.client", return_value=mock_client):
            response = handler({"httpMethod": "POST", "path": "/hit"}, None)

        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert body == {"count": n}, f"Expected {{'count': {n}}}, got {body}"


# ---------------------------------------------------------------------------
# Property 4: GET /count returns 0 when item absent
# Validates: Requirements 3.6, 5.4
# ---------------------------------------------------------------------------

class TestProperty4GetCountZeroWhenAbsent:
    """GET /count always returns {"count": 0} when the DynamoDB item is missing."""

    def test_returns_zero_on_empty_response(self):
        """GetItem returning {} (no 'Item' key) → count 0."""
        resource_mock, _ = _make_resource_mock(item=None)
        with patch.object(handler_module, "dynamodb", resource_mock):
            response = handler({"httpMethod": "GET", "path": "/count"}, None)
        assert response["statusCode"] == 200
        assert json.loads(response["body"]) == {"count": 0}

    def test_returns_zero_when_item_has_no_count_field(self):
        """Item present but missing 'count' attribute → count 0."""
        resource_mock, _ = _make_resource_mock(item={"id": "hits"})  # no count field
        with patch.object(handler_module, "dynamodb", resource_mock):
            response = handler({"httpMethod": "GET", "path": "/count"}, None)
        assert response["statusCode"] == 200
        assert json.loads(response["body"]) == {"count": 0}


# ---------------------------------------------------------------------------
# Property 5: GET /count returns the stored count for any N
# Validates: Requirements 3.6
# ---------------------------------------------------------------------------

class TestProperty5GetCountReturnsStoredCount:
    """GET /count reflects whatever count value is stored in DynamoDB."""

    @given(n=st.integers(min_value=0, max_value=10_000_000))
    @settings(max_examples=100)
    def test_status_200_and_count_equals_stored_value(self, n):
        resource_mock, _ = _make_resource_mock(
            item={"id": "hits", "count": Decimal(str(n))}
        )
        with patch.object(handler_module, "dynamodb", resource_mock):
            response = handler({"httpMethod": "GET", "path": "/count"}, None)

        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert body == {"count": n}, f"Expected {{'count': {n}}}, got {body}"


# ---------------------------------------------------------------------------
# Property 6: GET /count never calls UpdateItem
# Validates: Requirements 3.7
# ---------------------------------------------------------------------------

class TestProperty6GetCountNeverCallsUpdateItem:
    """UpdateItem must never be invoked for any GET /count invocation."""

    @given(n=st.integers(min_value=0, max_value=10_000_000))
    @settings(max_examples=50)
    def test_update_item_never_called(self, n):
        resource_mock, mock_table = _make_resource_mock(
            item={"id": "hits", "count": Decimal(str(n))}
        )
        with patch.object(handler_module, "dynamodb", resource_mock):
            handler({"httpMethod": "GET", "path": "/count"}, None)

        mock_table.update_item.assert_not_called()

    def test_update_item_not_called_when_item_absent(self):
        resource_mock, mock_table = _make_resource_mock(item=None)
        with patch.object(handler_module, "dynamodb", resource_mock):
            handler({"httpMethod": "GET", "path": "/count"}, None)
        mock_table.update_item.assert_not_called()


# ---------------------------------------------------------------------------
# Property 7: Counter item key is always {"id": {"S": "hits"}}
# Validates: Requirements 3.4
# ---------------------------------------------------------------------------

class TestProperty7CounterItemKeyIsHits:
    """The Key argument to UpdateItem must always be {"id": {"S": "hits"}}."""

    @given(n=st.integers(min_value=1, max_value=10_000_000))
    @settings(max_examples=50)
    def test_update_item_key_is_hits(self, n):
        mock_client = _make_client_mock(count=n)
        with patch("boto3.client", return_value=mock_client):
            handler({"httpMethod": "POST", "path": "/hit"}, None)

        kwargs = mock_client.update_item.call_args.kwargs
        assert kwargs["Key"] == {"id": {"S": "hits"}}, (
            f"Unexpected Key: {kwargs['Key']}"
        )

    def test_key_stable_on_first_write(self):
        """First-ever increment must still use the same key."""
        mock_client = _make_client_mock(count=1)
        with patch("boto3.client", return_value=mock_client):
            handler({"httpMethod": "POST", "path": "/hit"}, None)

        kwargs = mock_client.update_item.call_args.kwargs
        assert kwargs["Key"] == {"id": {"S": "hits"}}


# ---------------------------------------------------------------------------
# Property 8: DynamoDB throttle / transient errors → HTTP 503
# Validates: Requirements 3.8
# ---------------------------------------------------------------------------

_THROTTLE_CODES = [
    "ProvisionedThroughputExceededException",
    "ThrottlingException",
    "InternalServerError",
    "ServiceUnavailable",
    "RequestLimitExceeded",
]


class TestProperty8DynamoDbThrottleErrors:
    """ClientError with throttle/transient codes must produce HTTP 503."""

    @pytest.mark.parametrize("error_code", _THROTTLE_CODES)
    def test_post_hit_503_on_throttle_code(self, error_code):
        mock_client = _make_client_mock(update_raises=_client_error(error_code))
        with patch("boto3.client", return_value=mock_client):
            response = handler({"httpMethod": "POST", "path": "/hit"}, None)
        assert response["statusCode"] == 503
        assert json.loads(response["body"]) == {"error": "Service temporarily unavailable"}

    @pytest.mark.parametrize("error_code", _THROTTLE_CODES)
    def test_get_count_503_on_throttle_code(self, error_code):
        exc = ClientError(
            error_response={"Error": {"Code": error_code, "Message": "throttled"}},
            operation_name="GetItem",
        )
        resource_mock, _ = _make_resource_mock(get_item_raises=exc)
        with patch.object(handler_module, "dynamodb", resource_mock):
            response = handler({"httpMethod": "GET", "path": "/count"}, None)
        assert response["statusCode"] == 503
        assert json.loads(response["body"]) == {"error": "Service temporarily unavailable"}

    @given(error_code=st.sampled_from(_THROTTLE_CODES))
    @settings(max_examples=20)
    def test_property_post_hit_any_throttle_code(self, error_code):
        mock_client = _make_client_mock(update_raises=_client_error(error_code))
        with patch("boto3.client", return_value=mock_client):
            response = handler({"httpMethod": "POST", "path": "/hit"}, None)
        assert response["statusCode"] == 503


# ---------------------------------------------------------------------------
# Property 9: Any unexpected exception → HTTP 503
# Validates: Requirements 3.8
# ---------------------------------------------------------------------------

_EXCEPTION_FACTORIES = st.sampled_from([
    lambda: RuntimeError("unexpected runtime error"),
    lambda: ValueError("bad value"),
    lambda: KeyError("missing key"),
    lambda: MemoryError("oom"),
    lambda: OSError("io failure"),
])


class TestProperty9AnyExceptionProduces503:
    """Any non-ClientError exception from the DynamoDB call → HTTP 503."""

    @given(exc_factory=_EXCEPTION_FACTORIES)
    @settings(max_examples=50)
    def test_post_hit_503_on_any_exception(self, exc_factory):
        exc = exc_factory()
        mock_client = _make_client_mock(update_raises=exc)
        with patch("boto3.client", return_value=mock_client):
            response = handler({"httpMethod": "POST", "path": "/hit"}, None)
        assert response["statusCode"] == 503
        assert json.loads(response["body"]) == {"error": "Service temporarily unavailable"}

    @given(exc_factory=_EXCEPTION_FACTORIES)
    @settings(max_examples=50)
    def test_get_count_503_on_any_exception(self, exc_factory):
        exc = exc_factory()
        resource_mock, _ = _make_resource_mock(get_item_raises=exc)
        with patch.object(handler_module, "dynamodb", resource_mock):
            response = handler({"httpMethod": "GET", "path": "/count"}, None)
        assert response["statusCode"] == 503
        assert json.loads(response["body"]) == {"error": "Service temporarily unavailable"}


# ---------------------------------------------------------------------------
# Property 10: Unknown HTTP methods → HTTP 405
# Validates: Requirements 3.9
# ---------------------------------------------------------------------------

_UNKNOWN_METHODS = st.text(
    alphabet=st.characters(whitelist_categories=("Lu",)),  # uppercase letters
    min_size=1,
    max_size=20,
).filter(lambda m: m not in ("GET", "POST", "OPTIONS"))


class TestProperty10UnknownMethodReturns405:
    """Any HTTP method other than GET, POST, or OPTIONS must produce 405."""

    @given(method=_UNKNOWN_METHODS)
    @settings(max_examples=100)
    def test_unknown_method_returns_405(self, method):
        response = handler({"httpMethod": method, "path": "/hit"}, None)
        assert response["statusCode"] == 405
        assert json.loads(response["body"]) == {"error": "Method not allowed"}

    @pytest.mark.parametrize("method", ["DELETE", "PUT", "PATCH", "HEAD", "TRACE", "CONNECT"])
    def test_common_unknown_methods_return_405(self, method):
        response = handler({"httpMethod": method, "path": "/hit"}, None)
        assert response["statusCode"] == 405


# ---------------------------------------------------------------------------
# Property 11: Exactly one structured JSON log entry per invocation
# Validates: Requirements 6.4
# ---------------------------------------------------------------------------

class TestProperty11StructuredLogPerInvocation:
    """Every invocation must emit exactly one JSON log line containing 'status'."""

    def _assert_single_log(self, captured_out: str):
        lines = [line for line in captured_out.splitlines() if line.strip()]
        assert len(lines) == 1, (
            f"Expected exactly 1 log line, got {len(lines)}: {lines}"
        )
        entry = json.loads(lines[0])
        assert "status" in entry, f"Log entry missing 'status': {entry}"
        assert entry["status"] in ("ok", "error"), (
            f"'status' must be 'ok' or 'error', got {entry['status']!r}"
        )

    def test_log_on_get_count_success(self, capfd):
        resource_mock, _ = _make_resource_mock(item={"id": "hits", "count": Decimal("5")})
        with patch.object(handler_module, "dynamodb", resource_mock):
            handler({"httpMethod": "GET", "path": "/count"}, None)
        self._assert_single_log(capfd.readouterr().out)

    def test_log_on_get_count_absent(self, capfd):
        resource_mock, _ = _make_resource_mock(item=None)
        with patch.object(handler_module, "dynamodb", resource_mock):
            handler({"httpMethod": "GET", "path": "/count"}, None)
        self._assert_single_log(capfd.readouterr().out)

    def test_log_on_get_count_error(self, capfd):
        resource_mock, _ = _make_resource_mock(get_item_raises=_client_error())
        with patch.object(handler_module, "dynamodb", resource_mock):
            handler({"httpMethod": "GET", "path": "/count"}, None)
        entry = json.loads(capfd.readouterr().out.strip())
        assert entry["status"] == "error"

    def test_log_on_post_hit_success(self, capfd):
        mock_client = _make_client_mock(count=7)
        with patch("boto3.client", return_value=mock_client):
            handler({"httpMethod": "POST", "path": "/hit"}, None)
        self._assert_single_log(capfd.readouterr().out)

    def test_log_on_post_hit_error(self, capfd):
        mock_client = _make_client_mock(update_raises=_client_error())
        with patch("boto3.client", return_value=mock_client):
            handler({"httpMethod": "POST", "path": "/hit"}, None)
        entry = json.loads(capfd.readouterr().out.strip())
        assert entry["status"] == "error"

    def test_log_on_options(self, capfd):
        handler({"httpMethod": "OPTIONS", "path": "/hit"}, None)
        self._assert_single_log(capfd.readouterr().out)

    def test_log_on_405(self, capfd):
        handler({"httpMethod": "DELETE", "path": "/hit"}, None)
        entry = json.loads(capfd.readouterr().out.strip())
        assert entry["status"] == "error"

    def test_log_does_not_contain_pii(self, capfd):
        """Log must not include request body, headers, or PII."""
        resource_mock, _ = _make_resource_mock(item={"id": "hits", "count": Decimal("1")})
        with patch.object(handler_module, "dynamodb", resource_mock):
            handler({"httpMethod": "GET", "path": "/count",
                     "body": '{"secret": "password123"}'}, None)
        line = capfd.readouterr().out.strip()
        assert "password123" not in line
        assert "secret" not in line


# ===========================================================================
# Task 3.3 — Hypothesis property tests for the two-route Hit Handler
# ===========================================================================
# The handler was rewritten in task 3.1. It now has two routes:
#   POST /hit   → uses boto3.client (low-level), max_attempts=1
#   GET  /count → uses module-level boto3.resource
#
# Mocking strategy:
#   POST /hit:  patch("boto3.client") inside handler_module
#   GET /count: patch.object(handler_module, "dynamodb", ...)
# ===========================================================================

import contextlib
import io
from decimal import Decimal
from unittest.mock import MagicMock, call, patch

from botocore.exceptions import ClientError
from hypothesis import given, settings
from hypothesis import strategies as st

# ---------------------------------------------------------------------------
# Shared helpers for the two-route handler
# ---------------------------------------------------------------------------

# All routes & all outcomes that the handler can produce.
# Used by Properties 1 and 2 to cover every code path.
_ALL_EVENTS = [
    {"httpMethod": "POST", "path": "/hit"},
    {"httpMethod": "GET",  "path": "/count"},
    {"httpMethod": "OPTIONS", "path": "/hit"},
    {"httpMethod": "DELETE", "path": "/hit"},   # unknown → 405
]

_THROTTLE_CODES = [
    "ProvisionedThroughputExceededException",
    "ThrottlingException",
    "InternalServerError",
    "ServiceUnavailable",
    "RequestLimitExceeded",
]


def _make_client_mock_ok(count: int):
    """Return a mock boto3 client whose update_item returns *count*."""
    mock_client = MagicMock()
    mock_client.update_item.return_value = {
        "Attributes": {"count": {"N": str(count)}}
    }
    return mock_client


def _make_client_mock_error(exc: Exception):
    """Return a mock boto3 client whose update_item raises *exc*."""
    mock_client = MagicMock()
    mock_client.update_item.side_effect = exc
    return mock_client


def _make_resource_mock_ok(count: int):
    """Return a mock dynamodb resource whose Table.get_item returns *count*."""
    mock_table = MagicMock()
    mock_table.get_item.return_value = {"Item": {"id": "hits", "count": Decimal(count)}}
    mock_resource = MagicMock()
    mock_resource.Table.return_value = mock_table
    return mock_resource, mock_table


def _make_resource_mock_absent():
    """Return a mock dynamodb resource whose Table.get_item returns no item."""
    mock_table = MagicMock()
    mock_table.get_item.return_value = {}   # no "Item" key
    mock_resource = MagicMock()
    mock_resource.Table.return_value = mock_table
    return mock_resource, mock_table


def _make_resource_mock_error(exc: Exception):
    """Return a mock dynamodb resource whose Table.get_item raises *exc*."""
    mock_table = MagicMock()
    mock_table.get_item.side_effect = exc
    mock_resource = MagicMock()
    mock_resource.Table.return_value = mock_table
    return mock_resource, mock_table


def _client_error_with_code(code: str) -> ClientError:
    return ClientError(
        error_response={"Error": {"Code": code, "Message": "boom"}},
        operation_name="UpdateItem",
    )


# ---------------------------------------------------------------------------
# Property 1: CORS headers present on every response path
# Validates: Requirements 4.2
# ---------------------------------------------------------------------------

REQUIRED_CORS_KEYS = {
    "Access-Control-Allow-Origin",
    "Access-Control-Allow-Methods",
    "Access-Control-Allow-Headers",
}

REQUIRED_CACHE_CONTROL = "no-store"


def _invoke_all_paths_and_collect(event: dict) -> dict:
    """
    Invoke the handler for *event* with both a success mock and a failure mock,
    returning both responses as a dict keyed by 'ok' and 'err'.
    """
    responses = {}

    method = event.get("httpMethod", "")
    path   = event.get("path", "")

    # --- success path ---
    ok_client   = _make_client_mock_ok(42)
    ok_resource, _ = _make_resource_mock_ok(42)
    with patch("boto3.client", return_value=ok_client), \
         patch.object(handler_module, "dynamodb", ok_resource):
        responses["ok"] = handler(event, None)

    # --- error path (only meaningful for POST /hit and GET /count) ---
    err_exc     = _client_error_with_code("InternalServerError")
    err_client  = _make_client_mock_error(err_exc)
    err_resource, _ = _make_resource_mock_error(err_exc)
    with patch("boto3.client", return_value=err_client), \
         patch.object(handler_module, "dynamodb", err_resource):
        responses["err"] = handler(event, None)

    return responses


class TestProperty1CorsHeadersPresentOnEveryPath:
    """
    **Property 1**: CORS headers present on every response path.

    Validates: Requirements 4.2
    """

    def _assert_cors(self, response: dict, label: str) -> None:
        headers = response.get("headers", {})
        for key in REQUIRED_CORS_KEYS:
            assert key in headers, (
                f"[{label}] Missing CORS header: {key!r}. Headers: {headers}"
            )
        # Origin must not be empty
        assert headers["Access-Control-Allow-Origin"], (
            f"[{label}] Access-Control-Allow-Origin is empty"
        )

    @given(event=st.sampled_from(_ALL_EVENTS))
    @settings(max_examples=40)
    def test_cors_on_every_event_success_path(self, event: dict) -> None:
        """All events produce CORS headers on the happy path."""
        ok_client   = _make_client_mock_ok(1)
        ok_resource, _ = _make_resource_mock_ok(1)
        with patch("boto3.client", return_value=ok_client), \
             patch.object(handler_module, "dynamodb", ok_resource):
            resp = handler(event, None)
        self._assert_cors(resp, f"ok/{event.get('httpMethod')}{event.get('path')}")

    @given(event=st.sampled_from(_ALL_EVENTS))
    @settings(max_examples=40)
    def test_cors_on_every_event_error_path(self, event: dict) -> None:
        """All events produce CORS headers even when DynamoDB errors out."""
        err_exc    = _client_error_with_code("InternalServerError")
        err_client = _make_client_mock_error(err_exc)
        err_resource, _ = _make_resource_mock_error(err_exc)
        with patch("boto3.client", return_value=err_client), \
             patch.object(handler_module, "dynamodb", err_resource):
            resp = handler(event, None)
        self._assert_cors(resp, f"err/{event.get('httpMethod')}{event.get('path')}")


# ---------------------------------------------------------------------------
# Property 2: Cache-Control: no-store on every response path
# Validates: Requirements 6.5
# ---------------------------------------------------------------------------

class TestProperty2CacheControlNoStoreOnEveryPath:
    """
    **Property 2**: `Cache-Control: no-store` header present on every response.

    Validates: Requirements 6.5
    """

    def _assert_no_store(self, response: dict, label: str) -> None:
        headers = response.get("headers", {})
        cache_control = headers.get("Cache-Control", "")
        assert "no-store" in cache_control, (
            f"[{label}] Cache-Control header is {cache_control!r}, expected 'no-store'"
        )

    @given(event=st.sampled_from(_ALL_EVENTS))
    @settings(max_examples=40)
    def test_no_store_on_every_event_success_path(self, event: dict) -> None:
        ok_client   = _make_client_mock_ok(1)
        ok_resource, _ = _make_resource_mock_ok(1)
        with patch("boto3.client", return_value=ok_client), \
             patch.object(handler_module, "dynamodb", ok_resource):
            resp = handler(event, None)
        self._assert_no_store(resp, f"ok/{event.get('httpMethod')}")

    @given(event=st.sampled_from(_ALL_EVENTS))
    @settings(max_examples=40)
    def test_no_store_on_every_event_error_path(self, event: dict) -> None:
        err_exc    = _client_error_with_code("ThrottlingException")
        err_client = _make_client_mock_error(err_exc)
        err_resource, _ = _make_resource_mock_error(err_exc)
        with patch("boto3.client", return_value=err_client), \
             patch.object(handler_module, "dynamodb", err_resource):
            resp = handler(event, None)
        self._assert_no_store(resp, f"err/{event.get('httpMethod')}")


# ---------------------------------------------------------------------------
# Property 3: POST /hit returns the DynamoDB count value for any non-negative int
# Validates: Requirements 3.4
# ---------------------------------------------------------------------------

class TestProperty3PostHitReturnsDynamoDbCount:
    """
    **Property 3**: POST /hit returns HTTP 200 `{"count": n}` for any `n ≥ 0`
    returned by DynamoDB UpdateItem.

    Validates: Requirements 3.4
    """

    @given(n=st.integers(min_value=0, max_value=10_000_000))
    @settings(max_examples=100)
    def test_post_hit_returns_count_n(self, n: int) -> None:
        mock_client = _make_client_mock_ok(n)
        with patch("boto3.client", return_value=mock_client):
            resp = handler({"httpMethod": "POST", "path": "/hit"}, None)

        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        assert body == {"count": n}, f"Expected {{'count': {n}}}, got {body}"

    @given(n=st.integers(min_value=0, max_value=10_000_000))
    @settings(max_examples=50)
    def test_post_hit_count_type_is_int(self, n: int) -> None:
        """The `count` field in the response body must be an integer, not a string."""
        mock_client = _make_client_mock_ok(n)
        with patch("boto3.client", return_value=mock_client):
            resp = handler({"httpMethod": "POST", "path": "/hit"}, None)

        body = json.loads(resp["body"])
        assert isinstance(body["count"], int), (
            f"count should be int, got {type(body['count']).__name__}"
        )


# ---------------------------------------------------------------------------
# Property 4: GET /count returns 0 when counter item is absent
# Validates: Requirements 3.6, 5.4
# ---------------------------------------------------------------------------

class TestProperty4GetCountReturns0WhenAbsent:
    """
    **Property 4**: GET /count returns HTTP 200 `{"count": 0}` when the DynamoDB
    item does not exist.

    Validates: Requirements 3.6, 5.4
    """

    def test_returns_zero_when_item_absent(self) -> None:
        mock_resource, _ = _make_resource_mock_absent()
        with patch.object(handler_module, "dynamodb", mock_resource):
            resp = handler({"httpMethod": "GET", "path": "/count"}, None)

        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        assert body == {"count": 0}, f"Expected {{'count': 0}}, got {body}"

    def test_returns_zero_when_item_has_no_count_field(self) -> None:
        """Item exists but lacks the `count` attribute — still returns 0."""
        mock_table = MagicMock()
        mock_table.get_item.return_value = {"Item": {"id": "hits"}}  # no count
        mock_resource = MagicMock()
        mock_resource.Table.return_value = mock_table
        with patch.object(handler_module, "dynamodb", mock_resource):
            resp = handler({"httpMethod": "GET", "path": "/count"}, None)

        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        assert body == {"count": 0}

    # Drive the absent-item code path many times to ensure determinism
    @given(st.none())
    @settings(max_examples=30)
    def test_always_zero_when_absent(self, _) -> None:
        mock_resource, _ = _make_resource_mock_absent()
        with patch.object(handler_module, "dynamodb", mock_resource):
            resp = handler({"httpMethod": "GET", "path": "/count"}, None)

        body = json.loads(resp["body"])
        assert body["count"] == 0


# ---------------------------------------------------------------------------
# Property 5: GET /count returns stored count for any non-negative integer
# Validates: Requirements 3.6
# ---------------------------------------------------------------------------

class TestProperty5GetCountReturnsStoredCount:
    """
    **Property 5**: GET /count returns HTTP 200 `{"count": n}` for any `n ≥ 0`
    stored in DynamoDB.

    Validates: Requirements 3.6
    """

    @given(n=st.integers(min_value=0, max_value=10_000_000))
    @settings(max_examples=100)
    def test_get_count_returns_n(self, n: int) -> None:
        mock_resource, _ = _make_resource_mock_ok(n)
        with patch.object(handler_module, "dynamodb", mock_resource):
            resp = handler({"httpMethod": "GET", "path": "/count"}, None)

        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        assert body == {"count": n}, f"Expected {{'count': {n}}}, got {body}"

    @given(n=st.integers(min_value=0, max_value=10_000_000))
    @settings(max_examples=50)
    def test_get_count_value_type_is_int(self, n: int) -> None:
        mock_resource, _ = _make_resource_mock_ok(n)
        with patch.object(handler_module, "dynamodb", mock_resource):
            resp = handler({"httpMethod": "GET", "path": "/count"}, None)

        body = json.loads(resp["body"])
        assert isinstance(body["count"], int)


# ---------------------------------------------------------------------------
# Property 6: GET /count never calls UpdateItem
# Validates: Requirements 3.7
# ---------------------------------------------------------------------------

class TestProperty6GetCountNeverCallsUpdateItem:
    """
    **Property 6**: GET /count MUST NOT call DynamoDB `UpdateItem` under any
    circumstance — success, absent item, or error.

    Validates: Requirements 3.7
    """

    @given(n=st.integers(min_value=0, max_value=10_000_000))
    @settings(max_examples=50)
    def test_update_item_not_called_on_success(self, n: int) -> None:
        mock_resource, mock_table = _make_resource_mock_ok(n)
        with patch.object(handler_module, "dynamodb", mock_resource):
            handler({"httpMethod": "GET", "path": "/count"}, None)

        mock_table.update_item.assert_not_called()

    def test_update_item_not_called_when_absent(self) -> None:
        mock_resource, mock_table = _make_resource_mock_absent()
        with patch.object(handler_module, "dynamodb", mock_resource):
            handler({"httpMethod": "GET", "path": "/count"}, None)

        mock_table.update_item.assert_not_called()

    def test_update_item_not_called_on_get_item_error(self) -> None:
        err_exc = _client_error_with_code("InternalServerError")
        mock_resource, mock_table = _make_resource_mock_error(err_exc)
        with patch.object(handler_module, "dynamodb", mock_resource):
            handler({"httpMethod": "GET", "path": "/count"}, None)

        mock_table.update_item.assert_not_called()

    @given(event=st.sampled_from([
        {"httpMethod": "GET", "path": "/count"},
        {"httpMethod": "OPTIONS", "path": "/count"},
        {"httpMethod": "DELETE", "path": "/count"},
    ]))
    @settings(max_examples=30)
    def test_update_item_never_called_on_any_get_variant(self, event: dict) -> None:
        """Even unrecognised methods for /count must not trigger UpdateItem."""
        mock_resource, mock_table = _make_resource_mock_ok(7)
        # Also patch boto3.client to intercept any accidental client creation
        mock_client = MagicMock()
        with patch("boto3.client", return_value=mock_client), \
             patch.object(handler_module, "dynamodb", mock_resource):
            handler(event, None)

        mock_table.update_item.assert_not_called()
        mock_client.update_item.assert_not_called()


# ---------------------------------------------------------------------------
# Property 7: Counter item key is always {"id": {"S": "hits"}} (low-level client)
# Validates: Requirements 3.4
# ---------------------------------------------------------------------------

class TestProperty7CounterItemKeyIsAlwaysHits:
    """
    **Property 7**: POST /hit MUST always pass Key `{"id": {"S": "hits"}}` to
    the DynamoDB low-level client's `update_item`.

    Validates: Requirements 3.4
    """

    @given(n=st.integers(min_value=0, max_value=10_000_000))
    @settings(max_examples=50)
    def test_key_is_hits_on_success(self, n: int) -> None:
        mock_client = _make_client_mock_ok(n)
        with patch("boto3.client", return_value=mock_client):
            handler({"httpMethod": "POST", "path": "/hit"}, None)

        call_kwargs = mock_client.update_item.call_args.kwargs
        assert call_kwargs["Key"] == {"id": {"S": "hits"}}, (
            f"Expected Key={{'id': {{'S': 'hits'}}}}, got {call_kwargs.get('Key')}"
        )

    @given(code=st.sampled_from(_THROTTLE_CODES))
    @settings(max_examples=20)
    def test_key_is_hits_even_on_error(self, code: str) -> None:
        """Key must be correct even when DynamoDB raises."""
        err_exc    = _client_error_with_code(code)
        mock_client = _make_client_mock_error(err_exc)
        with patch("boto3.client", return_value=mock_client):
            handler({"httpMethod": "POST", "path": "/hit"}, None)

        call_kwargs = mock_client.update_item.call_args.kwargs
        assert call_kwargs["Key"] == {"id": {"S": "hits"}}

    def test_table_name_matches_env_var(self) -> None:
        """TableName in the update_item call must match TABLE_NAME env var."""
        mock_client = _make_client_mock_ok(1)
        with patch("boto3.client", return_value=mock_client):
            handler({"httpMethod": "POST", "path": "/hit"}, None)

        call_kwargs = mock_client.update_item.call_args.kwargs
        assert call_kwargs["TableName"] == os.environ["TABLE_NAME"]


# ---------------------------------------------------------------------------
# Property 8: DynamoDB throttle/transient ClientErrors produce HTTP 503
# Validates: Requirements 3.8
# ---------------------------------------------------------------------------

class TestProperty8ThrottleErrorsProduceHttp503:
    """
    **Property 8**: Any DynamoDB `ClientError` with a throttle/transient error
    code produces HTTP 503 with body `{"error": "Service temporarily unavailable"}`.

    Validates: Requirements 3.8
    """

    _POST_HIT_EVENT = {"httpMethod": "POST", "path": "/hit"}
    _GET_COUNT_EVENT = {"httpMethod": "GET", "path": "/count"}

    @given(code=st.sampled_from(_THROTTLE_CODES))
    @settings(max_examples=50)
    def test_post_hit_503_on_client_error(self, code: str) -> None:
        err_exc    = _client_error_with_code(code)
        mock_client = _make_client_mock_error(err_exc)
        with patch("boto3.client", return_value=mock_client):
            resp = handler(self._POST_HIT_EVENT, None)

        assert resp["statusCode"] == 503
        body = json.loads(resp["body"])
        assert body == {"error": "Service temporarily unavailable"}, (
            f"Unexpected body for {code}: {body}"
        )

    @given(code=st.sampled_from(_THROTTLE_CODES))
    @settings(max_examples=50)
    def test_get_count_503_on_client_error(self, code: str) -> None:
        err_exc = _client_error_with_code(code)
        mock_resource, _ = _make_resource_mock_error(err_exc)
        with patch.object(handler_module, "dynamodb", mock_resource):
            resp = handler(self._GET_COUNT_EVENT, None)

        assert resp["statusCode"] == 503
        body = json.loads(resp["body"])
        assert body == {"error": "Service temporarily unavailable"}

    @given(
        code=st.sampled_from(_THROTTLE_CODES),
        event=st.sampled_from([
            {"httpMethod": "POST", "path": "/hit"},
            {"httpMethod": "GET", "path": "/count"},
        ]),
    )
    @settings(max_examples=60)
    def test_503_body_never_leaks_error_code(self, code: str, event: dict) -> None:
        """The 503 body must not leak internal DynamoDB error codes."""
        err_exc    = _client_error_with_code(code)
        mock_client = _make_client_mock_error(err_exc)
        mock_resource, _ = _make_resource_mock_error(err_exc)
        with patch("boto3.client", return_value=mock_client), \
             patch.object(handler_module, "dynamodb", mock_resource):
            resp = handler(event, None)

        raw_body = resp["body"]
        assert code not in raw_body, (
            f"Error code {code!r} leaked into response body: {raw_body}"
        )


# ---------------------------------------------------------------------------
# Property 9: Any unexpected Python exception produces HTTP 503
# Validates: Requirements 3.8
# ---------------------------------------------------------------------------

_GENERIC_EXCEPTIONS = st.sampled_from([
    lambda: RuntimeError("unexpected"),
    lambda: ValueError("bad value"),
    lambda: TypeError("type mismatch"),
    lambda: ConnectionError("network gone"),
    lambda: MemoryError("oom"),
    lambda: KeyError("missing key"),
    lambda: AttributeError("no attr"),
])


class TestProperty9UnexpectedExceptionProducesHttp503:
    """
    **Property 9**: Any non-ClientError Python exception raised during handler
    execution produces HTTP 503 with body `{"error": "Service temporarily unavailable"}`.

    Validates: Requirements 3.8
    """

    @given(exc_factory=_GENERIC_EXCEPTIONS)
    @settings(max_examples=70)
    def test_post_hit_503_on_generic_exception(self, exc_factory) -> None:
        exc = exc_factory()
        mock_client = _make_client_mock_error(exc)
        with patch("boto3.client", return_value=mock_client):
            resp = handler({"httpMethod": "POST", "path": "/hit"}, None)

        assert resp["statusCode"] == 503
        body = json.loads(resp["body"])
        assert body == {"error": "Service temporarily unavailable"}, (
            f"Unexpected body for {type(exc).__name__}: {body}"
        )

    @given(exc_factory=_GENERIC_EXCEPTIONS)
    @settings(max_examples=70)
    def test_get_count_503_on_generic_exception(self, exc_factory) -> None:
        exc = exc_factory()
        mock_resource, _ = _make_resource_mock_error(exc)
        with patch.object(handler_module, "dynamodb", mock_resource):
            resp = handler({"httpMethod": "GET", "path": "/count"}, None)

        assert resp["statusCode"] == 503
        body = json.loads(resp["body"])
        assert body == {"error": "Service temporarily unavailable"}

    @given(exc_factory=_GENERIC_EXCEPTIONS)
    @settings(max_examples=50)
    def test_exception_type_not_leaked_in_body(self, exc_factory) -> None:
        """Exception class names must not appear in the response body (no PII/internals)."""
        exc = exc_factory()
        mock_client = _make_client_mock_error(exc)
        with patch("boto3.client", return_value=mock_client):
            resp = handler({"httpMethod": "POST", "path": "/hit"}, None)

        raw_body = resp["body"]
        assert type(exc).__name__ not in raw_body, (
            f"Exception type {type(exc).__name__!r} leaked into body: {raw_body}"
        )


# ---------------------------------------------------------------------------
# Property 10: Unknown HTTP methods produce HTTP 405
# Validates: Requirements 3.9
# ---------------------------------------------------------------------------

# Any string that is not GET, POST, or OPTIONS
_UNKNOWN_METHODS = st.text(
    alphabet=st.characters(whitelist_categories=("Lu",)),  # uppercase letters
    min_size=1,
    max_size=10,
).filter(lambda m: m not in {"GET", "POST", "OPTIONS"})

# Also test common-but-unrecognised verbs explicitly
_EXPLICIT_UNKNOWN_METHODS = st.sampled_from([
    "DELETE", "PUT", "PATCH", "HEAD", "TRACE", "CONNECT",
])


class TestProperty10UnknownMethodsProduceHttp405:
    """
    **Property 10**: Any HTTP method that is not `GET`, `POST`, or `OPTIONS`
    produces HTTP 405 with body `{"error": "Method not allowed"}`.

    Validates: Requirements 3.9
    """

    @given(method=_EXPLICIT_UNKNOWN_METHODS)
    @settings(max_examples=30)
    def test_unknown_verb_returns_405(self, method: str) -> None:
        resp = handler({"httpMethod": method, "path": "/hit"}, None)
        assert resp["statusCode"] == 405
        body = json.loads(resp["body"])
        assert body == {"error": "Method not allowed"}, (
            f"Method {method!r}: expected 405, got {resp['statusCode']}, body={body}"
        )

    @given(method=_UNKNOWN_METHODS)
    @settings(max_examples=50)
    def test_random_uppercase_verb_returns_405(self, method: str) -> None:
        resp = handler({"httpMethod": method, "path": "/hit"}, None)
        assert resp["statusCode"] == 405
        body = json.loads(resp["body"])
        assert body == {"error": "Method not allowed"}

    @given(method=_EXPLICIT_UNKNOWN_METHODS, path=st.sampled_from(["/hit", "/count", "/other"]))
    @settings(max_examples=30)
    def test_unknown_method_405_regardless_of_path(self, method: str, path: str) -> None:
        """405 must be returned for any path when method is not recognised."""
        resp = handler({"httpMethod": method, "path": path}, None)
        assert resp["statusCode"] == 405

    def test_empty_method_returns_405(self) -> None:
        """Empty httpMethod string must also return 405."""
        resp = handler({"httpMethod": "", "path": "/hit"}, None)
        assert resp["statusCode"] == 405

    def test_missing_method_key_returns_405(self) -> None:
        """Event with no httpMethod key must also return 405."""
        resp = handler({"path": "/hit"}, None)
        assert resp["statusCode"] == 405


def test_write_sdk_does_not_retry():
    with patch.object(handler_module.boto3, 'client') as client:
        client.return_value.update_item.return_value = {'Attributes': {'count': {'N': '1'}}}
        handler({'httpMethod': 'POST', 'path': '/hit'}, None)
        assert client.call_args.kwargs['config'].retries['total_max_attempts'] == 1


def test_cors_selects_only_configured_origin(monkeypatch):
    monkeypatch.setattr(handler_module, 'ALLOWED_ORIGIN', 'https://site.example')
    monkeypatch.setenv('EXTRA_ALLOWED_ORIGINS', '["http://localhost:5173"]')
    for origin, expected in [('http://localhost:5173', 'http://localhost:5173'), ('https://evil.example', 'https://site.example')]:
        response = handler({'httpMethod': 'OPTIONS', 'headers': {'Origin': origin}}, None)
        assert response['headers']['Access-Control-Allow-Origin'] == expected
