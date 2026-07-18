from fastapi import APIRouter

from app.api.routes import auth, health, imports, production_demands, replenishment, users


api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(imports.router)
api_router.include_router(replenishment.router)
api_router.include_router(production_demands.router)
