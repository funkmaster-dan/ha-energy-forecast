import asyncio

import aiohttp

from .protocol import valid_url


class AuthenticationError(Exception):
    pass


class ServiceError(Exception):
    pass


class Client:
    def __init__(self, session, url, token, site_id="home"):
        self.session = session
        self.url = valid_url(url)
        if site_id != "home":
            raise ValueError("API v1 uses site ID home")
        self.prefix = f"/v1/sites/{site_id}"
        self.token = token

    async def request(self, method, path, payload=None):
        try:
            async with self.session.request(
                method,
                self.url + self.prefix + path,
                json=payload,
                headers={"Authorization": "Bearer " + self.token},
                timeout=aiohttp.ClientTimeout(total=20),
                allow_redirects=False,
            ) as response:
                if response.status in (401, 403):
                    raise AuthenticationError("Pairing token rejected")
                if response.status >= 300:
                    raise ServiceError(f"Service returned HTTP {response.status}")
                result = await response.json()
                if path == "/forecast/latest" and result.get("schema_version") != "1.0":
                    raise ServiceError("Unsupported forecast schema")
                return result
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as error:
            raise ServiceError("Cannot communicate with Energy Forecast") from error

    async def latest(self):
        return await self.request("GET", "/forecast/latest")

    async def observations(self, batch):
        return await self.request("POST", "/observations", batch)

    async def diagnostics(self):
        return await self.request("GET", "/diagnostics")
