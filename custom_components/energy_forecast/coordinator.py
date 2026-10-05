from datetime import timedelta

from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .client import AuthenticationError, ServiceError
from .const import DOMAIN, POLL_SECONDS


class ForecastCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, entry, client):
        import logging

        super().__init__(
            hass,
            logging.getLogger(__name__),
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=POLL_SECONDS),
        )
        self.client = client

    async def _async_update_data(self):
        try:
            return await self.client.latest()
        except AuthenticationError as error:
            raise ConfigEntryAuthFailed from error
        except ServiceError as error:
            raise UpdateFailed("Forecast service unavailable") from error
