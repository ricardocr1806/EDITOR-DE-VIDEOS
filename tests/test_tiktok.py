"""Testes do agente do TikTok (sem rede: as chamadas HTTP são simuladas)."""

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlparse

from agente_tiktok import postar as tt

MB = 1024 * 1024


class Resp:
    def __init__(self, dados=None, status=200):
        self._d, self.status_code, self.text = dados or {}, status, json.dumps(dados or {})

    def json(self):
        return self._d


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.env = mock.patch.dict(os.environ, {"TIKTOK_CLIENT_KEY": "chave", "TIKTOK_CLIENT_SECRET": "segredo"})
        self.env.start()
        self.arq = mock.patch.object(tt, "ARQUIVO_TOKEN", self.tmp / "tok.json")
        self.arq.start()

    def tearDown(self):
        self.env.stop(); self.arq.stop()


class TestAutorizacao(Base):
    def test_link(self):
        q = parse_qs(urlparse(tt.link_autorizacao("xyz")).query)
        self.assertEqual(q["client_key"], ["chave"])
        self.assertEqual(q["scope"], ["user.info.basic,video.upload,video.publish"])
        self.assertEqual(q["redirect_uri"], [tt.REDIRECT_PADRAO])
        self.assertNotIn("segredo", tt.link_autorizacao())

    def test_extrai_codigo_da_url(self):
        url = "https://mentoria.ricardocastro.site/tiktok-callback?code=abc%2A123%21&scopes=x&state=s"
        self.assertEqual(tt.extrair_codigo(url), "abc*123!")
        self.assertEqual(tt.extrair_codigo("  abc  "), "abc")

    def test_recusa_vira_erro(self):
        with self.assertRaises(tt.ErroTikTok):
            tt.extrair_codigo("https://x/cb?error=access_denied&error_description=user+cancelled")

    def test_sem_chave_explica(self):
        with mock.patch.dict(os.environ, {"TIKTOK_CLIENT_KEY": ""}):
            with self.assertRaisesRegex(tt.ErroTikTok, "TIKTOK_CLIENT_KEY"):
                tt.link_autorizacao()

    def test_troca_e_renova(self):
        resposta = {"access_token": "A1", "refresh_token": "R1", "open_id": "u", "scope": "s",
                    "expires_in": 86400, "refresh_expires_in": 31536000}
        with mock.patch.object(tt.requests, "post", return_value=Resp(resposta)) as post:
            tt.trocar_codigo("https://x/cb?code=C")
            self.assertEqual(post.call_args.kwargs["data"]["code"], "C")
        self.assertEqual(oct(tt.ARQUIVO_TOKEN.stat().st_mode & 0o777), "0o600")
        self.assertEqual(tt.token_valido(), "A1")
        # expirado -> usa o refresh
        tok = json.loads(tt.ARQUIVO_TOKEN.read_text()); tok["expira_em"] = time.time() - 1
        tt.ARQUIVO_TOKEN.write_text(json.dumps(tok))
        with mock.patch.object(tt.requests, "post", return_value=Resp({**resposta, "access_token": "A2"})) as post:
            self.assertEqual(tt.token_valido(), "A2")
            self.assertEqual(post.call_args.kwargs["data"]["grant_type"], "refresh_token")
            self.assertEqual(post.call_args.kwargs["data"]["refresh_token"], "R1")


class TestPedacos(unittest.TestCase):
    def test_regras(self):
        self.assertEqual(tt.plano_de_pedacos(3 * MB), (3 * MB, 1))
        self.assertEqual(tt.plano_de_pedacos(64 * MB), (64 * MB, 1))
        chunk, total = tt.plano_de_pedacos(95 * MB)
        self.assertEqual((chunk, total), (10 * MB, 9))
        ultimo = 95 * MB - chunk * (total - 1)
        self.assertTrue(5 * MB <= ultimo <= 128 * MB)


class TestPostar(Base):
    def setUp(self):
        super().setUp()
        self.video = self.tmp / "v.mp4"
        self.video.write_bytes(b"x" * 1000)
        tt.ARQUIVO_TOKEN.write_text(json.dumps({"access_token": "A", "refresh_token": "R",
                                                "expira_em": time.time() + 9999}))

    def _rodar(self, modo, criador=None, privacidade=None):
        chamadas = []

        def post(url, json=None, **kw):
            chamadas.append((url, json))
            if url.endswith("creator_info/query/"):
                return Resp({"data": criador, "error": {"code": "ok"}})
            if url.endswith("status/fetch/"):
                return Resp({"data": {"status": "SEND_TO_USER_INBOX" if modo == "rascunho" else "PUBLISH_COMPLETE"},
                             "error": {"code": "ok"}})
            return Resp({"data": {"publish_id": "P1", "upload_url": "https://up/x"}, "error": {"code": "ok"}})

        with mock.patch.object(tt.requests, "post", side_effect=post), \
             mock.patch.object(tt.requests, "put", return_value=Resp(status=201)) as put:
            r = tt.postar(self.video, "minha legenda", modo, privacidade)
        return r, chamadas, put

    def test_rascunho(self):
        r, chamadas, put = self._rodar("rascunho")
        self.assertTrue(chamadas[0][0].endswith("/inbox/video/init/"))
        self.assertEqual(chamadas[0][1]["source_info"]["video_size"], 1000)
        self.assertEqual(put.call_args.kwargs["headers"]["Content-Range"], "bytes 0-999/1000")
        self.assertEqual(r["status"], "SEND_TO_USER_INBOX")

    def test_direto_respeita_privacidade_permitida(self):
        r, chamadas, _ = self._rodar("direto", {"privacy_level_options": ["SELF_ONLY"]})
        init = [c for c in chamadas if c[0].endswith("/publish/video/init/")][0][1]
        self.assertEqual(init["post_info"]["privacy_level"], "SELF_ONLY")
        self.assertEqual(init["post_info"]["title"], "minha legenda")
        self.assertEqual(r["status"], "PUBLISH_COMPLETE")

    def test_direto_privacidade_proibida(self):
        with self.assertRaises(tt.ErroTikTok):
            self._rodar("direto", {"privacy_level_options": ["SELF_ONLY"]}, "PUBLIC_TO_EVERYONE")

    def test_erro_da_api(self):
        with mock.patch.object(tt.requests, "post",
                               return_value=Resp({"error": {"code": "spam_risk_too_many_posts", "message": "x"}})):
            with self.assertRaisesRegex(tt.ErroTikTok, "spam_risk"):
                tt.postar(self.video, "", "rascunho")


if __name__ == "__main__":
    unittest.main()
