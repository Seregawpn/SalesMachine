import uuid

from project_os.secrets import get_api_key, set_api_key


def test_set_and_get_api_key_round_trips_through_keychain():
    service = f"com.projectos.test.{uuid.uuid4().hex}"
    account = "api_key"

    set_api_key(service, account, "test-secret-value-123")
    result = get_api_key(service, account)

    assert result == "test-secret-value-123"


def test_get_api_key_raises_clear_error_when_not_found():
    service = f"com.projectos.test.nonexistent.{uuid.uuid4().hex}"

    try:
        get_api_key(service, "api_key")
        assert False, "expected an exception for a missing keychain entry"
    except LookupError as e:
        assert service in str(e)
