from fastapi import Header, HTTPException


async def test_current_user_id(
    x_user_id: int | None = Header(None, alias="X-User-Id"),
) -> int:
    if x_user_id is None:
        raise HTTPException(status_code=401, detail="test actor required")
    return x_user_id


__all__ = ["test_current_user_id"]
