"""Testes do agente da Zernio (HTTP simulado)."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agente_tiktok import zernio as z


class Resp:
    def __init__(self, dados=None, status=200):
        self._d, self.status_code, self.text = dados if dados is not None else {}, status, json.dumps(dados)

    def json(self):
        return self._d


CONTAS = {"accounts": [{"_id": "acc1", "platform": "tiktok", "username": "isabeladuartesantos"},
                       {"_id": "acc2", "platform": "instagram", "username": "outra"}]}


class TestLegenda(unittest.TestCase):
    def test_tira_arrobas_mantem_hashtags_e_email(self):
        self.assertEqual(z.sem_arrobas("Fala @fulano.tal , olha isso #brasil @x"), "Fala, olha isso #brasil")
        self.assertEqual(z.sem_arrobas("contato: a@b.com"), "contato: a@b.com")
        self.assertEqual(z.sem_arrobas("linha 1 @a\n@b linha 2"), "linha 1\nlinha 2")


class TestPostar(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, {"ZERNIO_API_KEY": "sk_teste"})
        self.env.start()
        self.video = Path(tempfile.mkdtemp()) / "v.mp4"
        self.video.write_bytes(b"x" * 100)
        self.enviados = []

    def tearDown(self):
        self.env.stop()

    def _request(self, metodo, url, json=None, params=None, headers=None, **kw):
        self.assertEqual(headers["Authorization"], "Bearer sk_teste")
        self.enviados.append((metodo, url, json))
        if url.endswith("/accounts"):
            return Resp(CONTAS)
        if url.endswith("/creator-info"):
            return Resp({"privacyLevels": [{"value": "PUBLIC_TO_EVERYONE"}, {"value": "SELF_ONLY"}]})
        if url.endswith("/media/presign"):
            return Resp({"uploadUrl": "https://up", "publicUrl": "https://media.zernio.com/v.mp4"})
        if url.endswith("/posts"):
            return Resp({"post": {"_id": "p1", "status": "published", "platforms": [
                {"platform": "tiktok", "status": "published", "platformPostUrl": "https://tiktok.com/@i/video/1"}]}},
                status=201)
        raise AssertionError(url)

    def _rodar(self, **kw):
        with mock.patch.object(z.requests, "request", side_effect=self._request), \
             mock.patch.object(z.requests, "put", return_value=Resp(status=200)) as put:
            r = z.postar(self.video, "Notícia @perfil #politica", **kw)
        return r, put

    def test_publica_agora_publico_sem_arroba(self):
        r, put = self._rodar()
        corpo = [e for e in self.enviados if e[1].endswith("/posts")][0][2]
        self.assertEqual(corpo["content"], "Notícia #politica")
        self.assertTrue(corpo["publishNow"])
        self.assertEqual(corpo["platforms"], [{"platform": "tiktok", "accountId": "acc1"}])
        ts = corpo["tiktokSettings"]
        self.assertEqual(ts["privacy_level"], "PUBLIC_TO_EVERYONE")
        self.assertTrue(ts["content_preview_confirmed"] and ts["express_consent_given"])
        self.assertEqual(corpo["mediaItems"][0]["url"], "https://media.zernio.com/v.mp4")
        self.assertEqual(put.call_args.kwargs["headers"]["Content-Type"], "video/mp4")
        self.assertEqual(r["link"], "https://tiktok.com/@i/video/1")
        self.assertIsNone(r["erro"])

    def test_agendar(self):
        self._rodar(agendar="2026-11-03T18:00")
        corpo = [e for e in self.enviados if e[1].endswith("/posts")][0][2]
        self.assertNotIn("publishNow", corpo)
        self.assertEqual((corpo["scheduledFor"], corpo["timezone"]), ("2026-11-03T18:00", "America/Sao_Paulo"))

    def test_privacidade_indisponivel(self):
        with self.assertRaises(z.ErroZernio):
            self._rodar(privacidade="FOLLOWER_OF_CREATOR")

    def test_falha_parcial_207(self):
        def req(metodo, url, **kw):
            if url.endswith("/posts"):
                return Resp({"post": {"_id": "p1", "status": "failed", "platforms": [
                    {"platform": "tiktok", "status": "failed", "errorMessage": "video too short"}]}}, status=207)
            return self._request(metodo, url, **kw)
        with mock.patch.object(z.requests, "request", side_effect=req), \
             mock.patch.object(z.requests, "put", return_value=Resp(status=200)):
            r = z.postar(self.video, "x")
        self.assertEqual(r["erro"], "video too short")

    def test_sem_chave(self):
        with mock.patch.dict(os.environ, {"ZERNIO_API_KEY": ""}):
            with self.assertRaisesRegex(z.ErroZernio, "ZERNIO_API_KEY"):
                z.contas()

    def test_chave_invalida(self):
        with mock.patch.object(z.requests, "request", return_value=Resp({"error": "x"}, status=401)):
            with self.assertRaisesRegex(z.ErroZernio, "inválida"):
                z.contas()


if __name__ == "__main__":
    unittest.main()
