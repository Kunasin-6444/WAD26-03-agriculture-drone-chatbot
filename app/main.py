from fastapi import FastAPI

from app.api.webhook import router as webhook_router


app = FastAPI()


@app.get("/")
def root():
        return {
                "message": "Agriculture Drone Chatbot API is running!"
        }


app.include_router(webhook_router)