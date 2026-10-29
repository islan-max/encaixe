from fastapi import FastAPI


def create_app() -> FastAPI:
    app = FastAPI(title="Encaixe", docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/saude")
    def saude() -> dict[str, str]:
        # Sem tocar no banco: serve de ping para manter o Render acordado sem gastar o Neon.
        return {"estado": "ok"}

    return app


app = create_app()
