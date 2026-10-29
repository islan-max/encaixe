from fastapi.testclient import TestClient

from encaixe.app import create_app


def test_saude_responde_ok_sem_banco():
    resposta = TestClient(create_app()).get("/saude")
    assert resposta.status_code == 200
    assert resposta.json() == {"estado": "ok"}


def test_documentacao_automatica_fica_desligada():
    cliente = TestClient(create_app())
    for caminho in ("/docs", "/redoc", "/openapi.json"):
        assert cliente.get(caminho).status_code == 404
