from fastapi import APIRouter

router=APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
async def health():
        return {
            "code": 0,
            "message": "success",
            "data": {
                "status": "ok"
            }
        }
