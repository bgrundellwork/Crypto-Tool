from fastapi import FastAPI

from app.api.market import router as market_router

app = FastAPI(title="Crypto Market API")
app.include_router(market_router)


@app.get("/")
def root() -> dict[str, str]:
    return {"message": "Crypto Boom!"}
