import pytest
from fastapi.testclient import TestClient

from conftest import edit_memory
from main import create_app


@pytest.fixture
def client(env):
    from conftest import FakeBackend
    from config import Settings
    s = Settings(memory_path=env.memory, glossary_path=env.glossary, unseen_log=env.unseen, max_items=3)
    app = create_app(s, FakeBackend())
    return TestClient(app), env, s


def test_health_reports_languages_policy_and_counts(client):
    c, _, _ = client
    h = c.get("/health").json()
    assert h["status"] == "ok" and h["token_format"] == "numdash"
    lang = h["languages"]["ewondo"]
    assert lang["label"] == "Ewondo" and lang["fr_to_local"] and lang["local_to_fr"]
    assert lang["en_to_local"] and lang["local_to_en"]
    assert h["policy"]["allow_draft_memory"] is False and h["policy"]["strict_alert"] is True
    assert h["memory"]["entries"] >= 60 and h["glossary"]["terms"] >= 30


def test_translate_accepts_module1_payloads_and_keeps_ids_and_order(client):
    c, env, _ = client
    edit_memory(env.memory, "nav.continuer", "ewondo", "TRAD-CONTINUER")
    c.post("/reload")
    payloads = [
        {"id": "sl1", "text": "Continuer", "lang": "fr", "ctx": {"tag": "button", "step": 2}},
        {"id": "sl2", "text": "Frais : ⟦M1⟧", "lang": "fr", "ctx": {"tag": "span", "step": 2, "label": None}},
        {"id": "sl3", "text": "⟦M1⟧", "lang": None, "ctx": {}},
    ]
    r = c.post("/translate", json={"lang": "ewondo", "items": payloads})
    assert r.status_code == 200
    body = r.json()
    assert [x["id"] for x in body["results"]] == ["sl1", "sl2", "sl3"]
    assert body["results"][0]["text"] == "TRAD-CONTINUER" and body["results"][0]["source"] == "memory"
    assert body["results"][1]["status"] == "ok" and "⟦M1⟧" in body["results"][1]["text"]
    assert body["results"][2]["status"] == "passthrough"
    assert all(set(x) >= {"id", "text", "status", "source", "confidence", "needs_review", "reasons"} for x in body["results"])


def test_unknown_language_and_limits(client):
    c, _, _ = client
    assert c.post("/translate", json={"lang": "klingon", "items": [{"id": "a", "text": "x"}]}).status_code == 422
    assert c.post("/translate", json={"lang": "ewondo", "items": []}).status_code == 422
    too_many = [{"id": str(i), "text": "Texte numéro un"} for i in range(4)]
    assert c.post("/translate", json={"lang": "ewondo", "items": too_many}).status_code == 413
    assert c.post("/translate", json={"lang": "ewondo", "items": [{"id": "a", "text": "x", "lang": "de"}]}).status_code == 422


def test_bidirectional_directions_via_canonical_contract(client):
    c, env, _ = client
    edit_memory(env.memory, "nav.continuer", "ewondo", "TRAD-CONTINUER")
    c.post("/reload")
    # ewondo → français : la mémoire inverse est utilisée
    r = c.post("/translate", json={"source": "ewondo", "target": "fr",
                                   "items": [{"id": "r1", "text": "TRAD-CONTINUER", "lang": "ewondo"}]})
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "ewondo" and body["target"] == "fr"
    assert body["results"][0]["text"] == "Continuer" and body["results"][0]["source"] == "memory"
    # et la vue extension est aussi fournie
    assert body["translations"][0]["translated"] == "Continuer"
    assert body["translations"][0]["status"] == "human_validated"
    # direction inconnue → 422
    assert c.post("/translate", json={"source": "de", "target": "ewondo", "items": [{"id": "a", "text": "x"}]}).status_code == 422
    assert c.post("/translate", json={"source": "fr", "target": "bulu", "items": [{"id": "a", "text": "x"}]}).status_code == 422


def test_legacy_extension_contract(client):
    c, _, _ = client
    r = c.post("/translate", json={
        "source_language": "fr", "target_language": "ewondo",
        "texts": [{"id": "t1", "text": "Frais : ⟦M1⟧"}, "Paiement reçu"],
    })
    assert r.status_code == 200
    body = r.json()
    assert body["target"] == "ewondo" and body["lang"] == "ewondo"
    assert [t["id"] for t in body["translations"]] == ["t1", "t2"]
    assert body["translations"][1]["original"] == "Paiement reçu"
    assert set(body["translations"][0]) >= {"id", "original", "translated", "status", "warning"}


def test_cors_for_site_and_extension_only(client):
    c, _, _ = client
    ok = c.get("/health", headers={"Origin": "https://safinum.cm"})
    assert ok.headers.get("access-control-allow-origin") == "https://safinum.cm"
    assert "access-control-allow-origin" not in c.get("/health", headers={"Origin": "https://evil.example"}).headers
    pre = c.options("/translate", headers={"Origin": "https://safinum.cm", "Access-Control-Request-Method": "POST",
                                           "Access-Control-Request-Headers": "content-type",
                                           "Access-Control-Request-Private-Network": "true"})
    assert pre.status_code == 200 and pre.headers.get("access-control-allow-private-network") == "true"


def test_reload_picks_up_new_validations(client):
    c, env, _ = client
    body = {"lang": "ewondo", "items": [{"id": "a", "text": "Retour"}]}
    assert c.post("/translate", json=body).json()["results"][0]["source"] == "mt"
    edit_memory(env.memory, "nav.retour", "ewondo", "TRAD-RETOUR")
    assert c.post("/reload").json()["memory"]["by_language"]["ewondo"]["validated"] == 1
    assert c.post("/translate", json=body).json()["results"][0]["text"] == "TRAD-RETOUR"
