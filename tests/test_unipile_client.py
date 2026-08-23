from unittest.mock import patch, MagicMock

from project_os.integrations.unipile_client import UnipileClient


def test_get_accounts_sends_correct_request_and_parses_response():
    client = UnipileClient(api_key="test-key", base_url="https://api40.unipile.com:17075/api/v1")

    fake_response = MagicMock()
    fake_response.json.return_value = {"items": [{"id": "acc_1", "type": "LINKEDIN"}]}
    fake_response.raise_for_status.return_value = None

    with patch("project_os.integrations.unipile_client.requests.get", return_value=fake_response) as mock_get:
        accounts = client.get_accounts()

    mock_get.assert_called_once_with(
        "https://api40.unipile.com:17075/api/v1/accounts",
        headers={"X-API-KEY": "test-key", "accept": "application/json"},
        timeout=10,
    )
    assert accounts == [{"id": "acc_1", "type": "LINKEDIN"}]
