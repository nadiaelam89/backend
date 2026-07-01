import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_public_pixels_endpoint(client: AsyncClient) -> None:
    response = await client.get("/api/public/pixels")
    assert response.status_code == 200
    data = response.json()
    assert set(data.keys()) == {"meta", "tiktok", "snap"}
    assert all(isinstance(value, str) for value in data.values())
