from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any

import httpx

from exchanges.okx.signer import sign_okx_request


class OKXRestClient:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        secret_key: str | None = None,
        passphrase: str | None = None,
        base_url: str = "https://www.okx.com",
        timeout: float = 10.0,
    ) -> None:
        self.api_key = api_key
        self.secret_key = secret_key
        self.passphrase = passphrase
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _timestamp(self) -> str:
        return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")

    def _headers(self, method: str, request_path: str, body: str = "") -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key and self.secret_key and self.passphrase:
            timestamp = self._timestamp()
            headers.update(
                {
                    "OK-ACCESS-KEY": self.api_key,
                    "OK-ACCESS-SIGN": sign_okx_request(
                        timestamp, method, request_path, body, self.secret_key
                    ),
                    "OK-ACCESS-TIMESTAMP": timestamp,
                    "OK-ACCESS-PASSPHRASE": self.passphrase,
                }
            )
        return headers

    def get(self, path: str, params: dict[str, Any] | None = None, *, private: bool = False) -> dict:
        query = ""
        if params:
            query = "?" + "&".join(f"{key}={value}" for key, value in params.items())
        request_path = f"{path}{query}"
        headers = self._headers("GET", request_path) if private else {"Content-Type": "application/json"}
        response = httpx.get(
            f"{self.base_url}{path}",
            params=params,
            headers=headers,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def post(self, path: str, body: dict[str, Any], *, private: bool = False) -> dict:
        body_text = json.dumps(body, separators=(",", ":"))
        headers = self._headers("POST", path, body_text) if private else {"Content-Type": "application/json"}
        response = httpx.post(
            f"{self.base_url}{path}",
            content=body_text,
            headers=headers,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()
