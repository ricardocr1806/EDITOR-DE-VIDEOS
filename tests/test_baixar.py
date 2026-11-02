"""Testes do agente de download. Rodar com: python -m unittest discover tests"""

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agente_instagram import baixar


class TestLinks(unittest.TestCase):
    def test_aceita_links_do_instagram(self):
        for link in [
            "https://www.instagram.com/reel/C5qJ1yDOuWm/",
            "https://instagram.com/p/ABC123/",
            "https://www.instagram.com/reels/C5qJ1yDOuWm/",
            "https://www.instagram.com/tv/ABC123/",
            "https://www.instagram.com/stories/fulano/3312345678901234567/",
            "https://www.instagram.com/fulano/reel/C5qJ1yDOuWm/",
            "https://instagr.am/p/ABC123/",
        ]:
            self.assertTrue(baixar.link_valido(link), link)

    def test_recusa_outros_links(self):
        for link in [
            "https://www.instagram.com/fulano/",
            "https://www.youtube.com/watch?v=abc",
            "instagram.com/reel/abc",
            "https://evil.com/instagram.com/reel/abc",
        ]:
            self.assertFalse(baixar.link_valido(link), link)

    def test_tira_rastreio(self):
        self.assertEqual(
            baixar.limpar_link("https://www.instagram.com/reel/C5q/?igsh=abc123&utm_source=x"),
            "https://www.instagram.com/reel/C5q/",
        )

    def test_link_invalido_vira_erro_explicado(self):
        r = baixar.baixar_um("https://www.youtube.com/watch?v=abc", Path(tempfile.mkdtemp()))
        self.assertEqual(r.status, "erro")
        self.assertIn("Compartilhar", r.dica)

    def test_dicas_de_erro(self):
        self.assertIn("cookies", baixar.explicar_erro("Requested content is not available, rate-limit reached or login required"))
        self.assertIn("privado", baixar.explicar_erro("This account is private"))
        self.assertIn("só foto", baixar.explicar_erro("There is no video in this post"))

    def test_lista_ignora_comentarios_e_duplicados(self):
        with tempfile.TemporaryDirectory() as d:
            lista = Path(d) / "links.txt"
            lista.write_text("# meus reels\nhttps://instagram.com/reel/A/\n\nhttps://instagram.com/reel/A/?igsh=x\n")
            links = baixar.ler_lista(lista)
            self.assertEqual(len(links), 2)
            with mock.patch.object(baixar, "baixar_um", return_value=baixar.Resultado("x", "baixado")) as m:
                baixar.baixar_varios(links, Path(d))
            self.assertEqual(m.call_count, 1)


@unittest.skipUnless(shutil.which("ffmpeg"), "precisa do ffmpeg")
class TestDownloadDeVerdade(unittest.TestCase):
    """Usa um vídeo local (file://) no lugar do Instagram para testar o caminho inteiro."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.origem = self.tmp / "fonte" / "video_teste.mp4"
        self.origem.parent.mkdir()
        subprocess.run([
            "ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=1080x1920:rate=30:duration=2",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-shortest",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(self.origem),
        ], check=True)
        self.saida = self.tmp / "originais"
        opcoes_reais = baixar._opcoes_ytdlp
        self.patch = mock.patch.object(
            baixar, "_opcoes_ytdlp",
            lambda *a: {**opcoes_reais(*a), "enable_file_urls": True},
        )
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        shutil.rmtree(self.tmp)

    def test_baixa_mede_e_nao_sobrescreve(self):
        link = self.origem.as_uri()
        r = baixar.baixar_um(link, self.saida, validar=False)
        self.assertEqual(r.status, "baixado", r.erro)
        video = Path(r.arquivos[0])
        self.assertTrue(video.exists())
        self.assertEqual(video.suffix, ".mp4")

        ficha = json.loads(video.with_suffix(".json").read_text())
        self.assertEqual((ficha["largura"], ficha["altura"]), (1080, 1920))
        self.assertEqual(ficha["fps"], 30)
        self.assertAlmostEqual(ficha["duracao_s"], 2, delta=0.1)

        antes = video.stat().st_mtime_ns
        r2 = baixar.baixar_um(link, self.saida, validar=False)
        self.assertEqual(r2.status, "ja_existia")
        self.assertEqual(video.stat().st_mtime_ns, antes)


if __name__ == "__main__":
    unittest.main()
