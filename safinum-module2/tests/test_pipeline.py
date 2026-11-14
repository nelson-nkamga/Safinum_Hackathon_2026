import json
import re

from conftest import edit_glossary, edit_memory
from pipeline import Item
from textutil import find_tokens


def run(pipe, text, lang="ewondo", **kw):
    return pipe.translate_batch(lang, [Item("t1", text, **kw)])[0]


# ------------------------------------------------------------------ mémoire (étapes 1-2)
def test_memory_hit_returns_human_translation_without_calling_model(env):
    edit_memory(env.memory, "nav.continuer", "ewondo", "TRAD-CONTINUER")
    pipe, backend, _ = env.build()
    r = run(pipe, "Continuer")
    assert (r.status, r.source, r.text, r.confidence) == ("ok", "memory", "TRAD-CONTINUER", 1.0)
    assert backend.calls == []


def test_memory_key_is_tolerant_to_case_spaces_final_dot(env):
    edit_memory(env.memory, "nav.continuer", "ewondo", "TRAD-CONTINUER")
    pipe, _, _ = env.build()
    for variant in ["continuer", "  CONTINUER  ", "Continuer."]:
        assert run(pipe, variant).source == "memory", variant


def test_memory_parameterized_with_module1_tokens(env):
    edit_memory(env.memory, "anticipe.frais_mm", "ewondo", "FRAIS-EW : ⟦M1⟧")
    pipe, _, _ = env.build()
    r = run(pipe, "Frais de transfert : ⟦M1⟧")
    assert r.text == "FRAIS-EW : ⟦M1⟧" and find_tokens(r.text) == find_tokens("⟦M1⟧")


def test_memory_drafts_ignored_by_default_and_flagged_when_allowed(env):
    edit_memory(env.memory, "nav.continuer", "ewondo", "BROUILLON", status="draft")
    pipe, backend, _ = env.build()
    assert run(pipe, "Continuer").source == "mt"        # brouillon ignoré → traduction automatique contrôlée
    pipe2, _, _ = env.build(allow_draft_memory=True)
    r = run(pipe2, "Continuer")
    assert (r.source, r.needs_review, r.text) == ("memory_draft", True, "BROUILLON")


def test_memory_entry_with_wrong_tokens_is_rejected_at_load(env):
    edit_memory(env.memory, "anticipe.frais_mm", "ewondo", "FRAIS-EW sans jeton")
    pipe, _, _ = env.build()
    assert any("jetons différents" in w for w in pipe.memory.warnings)
    assert run(pipe, "Frais de transfert : ⟦M1⟧").source != "memory"


def test_unsupported_target_language_falls_back(env):
    edit_memory(env.memory, "nav.continuer", "ewondo", "TRAD-CONTINUER")
    pipe, _, _ = env.build()
    r = run(pipe, "Continuer", lang="bulu")
    assert r.status == "fallback" and r.reasons[0].startswith("unsupported_direction")


def test_reverse_direction_uses_validated_memory(env):
    edit_memory(env.memory, "nav.continuer", "ewondo", "EW-CONTINUER")
    pipe, backend, _ = env.build()
    r = pipe.translate_items("ewondo", "fr", [Item("r1", "EW-CONTINUER", "ewondo")])[0]
    assert (r.status, r.source, r.text) == ("ok", "memory", "Continuer")
    assert backend.calls == []


def test_reverse_direction_machine_translation_and_roundtrip(env):
    pipe, backend, _ = env.build()
    r = pipe.translate_items("ewondo", "fr", [Item("r1", "Mbolo", "ewondo")])[0]
    assert r.status == "ok" and r.source == "mt"
    assert [c[0] for c in backend.calls] == ["ewondo-francais", "francais-ewondo"]


# ------------------------------------------------------------------ glossaire (étapes 3-4, 6)
def test_keep_terms_are_tokenized_for_the_model_and_restored(env):
    pipe, backend, _ = env.build()
    r = run(pipe, "Paiement reçu par Mobile Money en FCFA")
    sent = backend.calls[0][1][0]
    assert re.search(r"NUM-?\d", sent) and "Mobile Money" not in sent and "FCFA" not in sent
    assert r.status == "ok" and "Mobile Money" in r.text and "FCFA" in r.text and "G1" not in r.text


def test_validated_glossary_translation_is_inserted_with_case(env):
    edit_glossary(env.glossary, "solde", "ewondo", "nsolo")
    pipe, backend, _ = env.build()
    r = run(pipe, "Solde minimum requis")
    assert r.status == "ok" and r.text.startswith("[ew] ") and "Nsolo" in r.text
    assert "Solde" not in backend.calls[0][1][0]


def test_unvalidated_glossary_term_is_left_to_the_model(env):
    pipe, backend, _ = env.build()
    run(pipe, "Solde minimum requis")
    assert "Solde" in backend.calls[0][1][0]


def test_text_made_only_of_glossary_terms_skips_the_model(env):
    edit_glossary(env.glossary, "solde", "ewondo", "nsolo")
    edit_glossary(env.glossary, "total", "ewondo", "ntot")
    pipe, backend, _ = env.build()
    r = run(pipe, "Solde total")
    assert (r.status, r.source, r.text) == ("ok", "glossary", "Nsolo ntot")
    assert backend.calls == []


def test_module1_tokens_are_never_touched_by_the_glossary(env):
    pipe, backend, _ = env.build()
    r = run(pipe, "Frais : ⟦M1⟧ pour le transfert ⟦T1⟧ vers ⟦N1⟧")
    assert r.status == "ok" and find_tokens(r.text) == find_tokens("⟦M1⟧ ⟦T1⟧ ⟦N1⟧")


# ------------------------------------------------------------------ phrases inédites (étapes 5-8)
def test_unseen_sentence_is_translated_validated_and_accepted(env):
    pipe, backend, _ = env.build()
    r = run(pipe, "Veuillez confirmer votre opération.")
    assert r.status == "ok" and r.source == "mt" and r.text.startswith("[ew] ")
    assert r.back_translation == "Veuillez confirmer votre opération." and r.confidence >= 0.9
    assert [c[0] for c in backend.calls] == ["francais-ewondo", "ewondo-francais"]


def test_token_encoding_sent_to_model_follows_setting(env):
    pipe, backend, _ = env.build(token_format="alnum")
    run(pipe, "Votre compte sera débité de ⟦M1⟧ demain")
    assert "QM1Q" in backend.calls[0][1][0] and "⟦" not in backend.calls[0][1][0]


def test_multi_sentence_text_is_translated_sentence_by_sentence(env):
    pipe, backend, _ = env.build()
    r = run(pipe, "Première phrase ici. Deuxième phrase là.")
    assert backend.calls[0][1] == ["Première phrase ici.", "Deuxième phrase là."]
    assert r.status == "ok"


def test_model_losing_a_token_falls_back_to_original_text(env):
    # on désactive le nouvel essai automatique de formats pour tester le repli
    pipe, _, _ = env.build(mode="drop_tokens", token_format="square", token_retry_formats=())
    src = "Vous allez envoyer ⟦M1⟧ vers la banque"
    r = run(pipe, src)
    assert r.status == "fallback" and r.text == src and any(x.startswith("token_missing") for x in r.reasons)


def test_translator_retries_another_token_format_before_giving_up(env):
    pipe, backend, _ = env.build(mode="drop_square", token_format="square")
    src = "Vous allez envoyer ⟦M1⟧ vers la banque"
    r = run(pipe, src)
    assert r.status == "ok" and "⟦M1⟧" in r.text
    fwd = [texts for pair, texts in backend.calls if pair == "francais-ewondo"]
    assert any("[[" in " ".join(t) for t in fwd)          # 1er essai : format square
    assert any("NUM" in " ".join(t) for t in fwd)         # nouvel essai : format numérique


def test_changed_digits_fall_back(env):
    pipe, _, _ = env.build(mode="digits")
    r = run(pipe, "Étape 2 sur 5 du parcours")
    assert r.status == "fallback" and "digits_changed" in r.reasons


def test_low_back_translation_falls_back(env):
    pipe, _, _ = env.build(mode="bad_back")
    r = run(pipe, "Veuillez confirmer votre opération.")
    assert r.status == "fallback" and r.text == "Veuillez confirmer votre opération."
    assert r.reasons[0].startswith("back_translation_low")


def test_copy_of_source_and_garbage_fall_back(env):
    pipe, _, _ = env.build(mode="copy")
    assert "copy_of_source" in run(pipe, "Veuillez confirmer votre opération.").reasons
    pipe2, _, _ = env.build(mode="garbage")
    assert run(pipe2, "Veuillez confirmer votre opération.").status == "fallback"


# ------------------------------------------------------------------ politique de sécurité
def test_security_warning_never_uses_unvalidated_machine_translation(env):
    pipe, backend, _ = env.build()
    r = run(pipe, "Attention : cette opération est irréversible.", ctx={"alert": "warning"})
    assert r.status == "fallback" and r.reasons == ["alert_requires_validated_translation"]
    assert backend.calls == []


def test_security_warning_uses_memory_when_validated(env):
    edit_memory(env.memory, "benef.avert_nouveau", "ewondo", "AVERT-EW")
    pipe, _, _ = env.build()
    r = run(pipe, "Ce bénéficiaire n'a jamais été utilisé sur ce compte. Vérifiez le numéro avant de continuer.",
            ctx={"alert": "warning"})
    assert (r.status, r.source, r.text) == ("ok", "memory", "AVERT-EW")


def test_sensitive_text_is_rejected_not_translated_not_logged(env):
    pipe, backend, _ = env.build()
    for text in ["Total 25 000 FCFA à débiter", "Appelez +237 6 99 12 34 56", "Écrire à jean@mail.cm"]:
        r = run(pipe, text)
        assert r.status == "rejected" and r.text == text and r.reasons[0].startswith("sensitive:")
    assert backend.calls == [] and not env.unseen.exists()


def test_tokens_only_text_is_passthrough(env):
    pipe, backend, _ = env.build()
    r = run(pipe, "⟦M1⟧")
    assert (r.status, r.text) == ("passthrough", "⟦M1⟧") and backend.calls == []


def test_missing_direction_falls_back(env):
    pipe, _, _ = env.build(pairs={"ewondo-francais", "english-francais", "francais-english"})
    r = run(pipe, "Veuillez confirmer votre opération.", lang="ewondo")
    assert r.status == "fallback" and r.reasons == ["direction_unavailable"]


def test_engine_crash_falls_back_for_every_item(env):
    pipe, backend, _ = env.build()
    backend.translate = lambda pair, texts: (_ for _ in ()).throw(RuntimeError("boom"))
    rs = pipe.translate_batch("ewondo", [Item("a", "Texte inédit un"), Item("b", "Texte inédit deux")])
    assert [r.status for r in rs] == ["fallback", "fallback"] and rs[0].reasons == ["engine_error:RuntimeError"]


# ------------------------------------------------------------------ anglais (pivot)
def test_english_text_uses_memory_en_key(env):
    data = json.loads(env.memory.read_text(encoding="utf-8"))
    for e in data["entries"]:
        if e["id"] == "nav.continuer":
            e["en"] = "Continue"
    env.memory.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    edit_memory(env.memory, "nav.continuer", "ewondo", "TRAD-CONTINUER")
    pipe, _, _ = env.build()
    r = pipe.translate_batch("ewondo", [Item("e1", "Continue", "en")])[0]
    assert (r.source, r.text) == ("memory", "TRAD-CONTINUER")


def test_english_pivot_hits_validated_french_memory(env):
    edit_memory(env.memory, "nav.continuer", "ewondo", "TRAD-CONTINUER")
    pipe, _, _ = env.build(en_fr={"Next": "Continuer"})
    r = pipe.translate_batch("ewondo", [Item("e1", "Next", "en")])[0]
    assert r.status == "ok" and r.source == "memory" and "via_pivot_en" in r.reasons


def test_english_unseen_pivot_can_be_refused_by_policy(env):
    pipe, _, _ = env.build(allow_pivot_mt=False,
                           en_fr={"Please confirm your operation": "Veuillez confirmer votre opération"})
    r = pipe.translate_batch("ewondo", [Item("e1", "Please confirm your operation", "en")])[0]
    assert r.status == "fallback" and r.text == "Please confirm your operation" and r.reasons == ["pivot_en_unvalidated"]


def test_english_unseen_is_translated_via_pivot_and_marked_for_review(env):
    pipe, _, _ = env.build(
        en_fr={"Please confirm your operation": "Veuillez confirmer votre opération"},
        fr_en={"Veuillez confirmer votre opération": "Please confirm your operation"},
    )
    r = pipe.translate_batch("ewondo", [Item("e1", "Please confirm your operation", "en")])[0]
    assert r.status == "ok" and r.source == "mt"
    assert r.needs_review is True and "via_pivot_en" in r.reasons


def test_english_without_pivot_direction_falls_back(env):
    pipe, _, _ = env.build(pairs={"francais-ewondo", "ewondo-francais"})
    r = pipe.translate_batch("ewondo", [Item("e1", "Hello world today", "en")])[0]
    assert r.reasons == ["pivot_en_unavailable"]


# ------------------------------------------------------------------ phrases inédites journalisées
def test_unseen_masked_texts_are_logged_once_without_sensitive_data(env):
    pipe, _, _ = env.build()
    run(pipe, "Votre compte sera débité de ⟦M1⟧ demain")
    run(pipe, "Votre compte sera débité de ⟦M1⟧ demain")
    lines = env.unseen.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1 and json.loads(lines[0])["fr"] == "Votre compte sera débité de ⟦M1⟧ demain"
