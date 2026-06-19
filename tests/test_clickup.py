import asyncio

from clickcal.clickup import ClickUpClient, _parse_location


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeAsyncClient:
    """Returns canned payloads based on the requested path."""

    def __init__(self, routes):
        self._routes = routes

    async def get(self, path, params=None):
        return _FakeResponse(self._routes[path])

    async def aclose(self):
        return None


def test_get_space_lists_excludes_archived_lists_and_folders():
    routes = {
        "/space/S/list": {
            "lists": [
                {"id": 1, "name": "Active folderless", "archived": False},
                {"id": 2, "name": "Archived folderless", "archived": True},
            ]
        },
        "/space/S/folder": {
            "folders": [
                {
                    "name": "Active folder",
                    "archived": False,
                    "lists": [
                        {"id": 3, "name": "Active in folder", "archived": False},
                        {"id": 4, "name": "Archived in folder", "archived": True},
                    ],
                },
                {
                    "name": "Archived folder",
                    "archived": True,
                    "lists": [
                        {"id": 5, "name": "List in archived folder", "archived": False},
                    ],
                },
            ]
        },
    }
    client = ClickUpClient("token", client=_FakeAsyncClient(routes))
    lists = asyncio.run(client.get_space_lists("S"))
    names = [lst.name for lst in lists]
    assert names == ["Active folderless", "Active in folder"]


def test_parse_location_from_custom_field():
    fields = [
        {"name": "Other", "type": "short_text", "value": "x"},
        {
            "name": "Location Details",
            "type": "location",
            "value": {
                "location": {"lat": 52.0, "lng": 13.0},
                "formatted_address": "Berlin, Germany",
            },
        },
    ]
    assert _parse_location(fields) == "Berlin, Germany"


def test_parse_location_skips_empty_location_fields():
    fields = [
        {"name": "Location Details", "type": "location", "value": None},
        {
            "name": "Venue",
            "type": "location",
            "value": {"formatted_address": "Leipzig, Germany"},
        },
    ]
    assert _parse_location(fields) == "Leipzig, Germany"


def test_parse_location_returns_empty_when_absent():
    assert _parse_location([{"name": "Link", "type": "url", "value": "https://x"}]) == ""
    assert _parse_location([]) == ""
    assert _parse_location(None) == ""
