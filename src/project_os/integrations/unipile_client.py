import requests


class UnipileClient:
    def __init__(self, api_key: str, base_url: str = "https://api40.unipile.com:17075/api/v1"):
        self.api_key = api_key
        self.base_url = base_url

    def _headers(self) -> dict:
        return {"X-API-KEY": self.api_key, "accept": "application/json"}

    def get_accounts(self) -> list[dict]:
        response = requests.get(
            f"{self.base_url}/accounts",
            headers=self._headers(),
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()
        return data["items"] if isinstance(data, dict) and "items" in data else data
