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


def _gerar(destino, codec_video, codec_audio="aac", sem_video=False):
    cmd = ["ffmpeg", "-y", "-v", "error"]
    if not sem_video:
        cmd += ["-f", "lavfi", "-i", "testsrc=size=360x640:rate=30:duration=1"]
    cmd += ["-f", "lavfi", "-i", "sine=frequency=440:duration=1", "-shortest"]
    if not sem_video:
        cmd += ["-c:v", codec_video, "-pix_fmt", "yuv420p"]
        if codec_video == "libaom-av1":
            cmd += ["-cpu-used", "8", "-crf", "50"]
    cmd += ["-c:a", codec_audio, str(destino)]
    subprocess.run(cmd, check=True)
    return destino


@unittest.skipUnless(shutil.which("ffmpeg"), "precisa do ffmpeg")
class TestSoAudioNoMac(unittest.TestCase):
    """O problema real: o Instagram manda VP9/AV1 e o QuickTime toca só o áudio."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_vp9_vira_h264(self):
        f = _gerar(self.tmp / "vp9.mp4", "libvpx-vp9", "libopus")
        self.assertFalse(baixar.abre_em_qualquer_lugar(baixar.inspecionar(f)))
        self.assertTrue(baixar.garantir_compativel(f))
        info = baixar.inspecionar(f)
        self.assertEqual((info["video"], info["audio"]), ("h264", "aac"))
        self.assertFalse((self.tmp / "vp9.convertendo.mp4").exists())

    def test_av1_vira_h264(self):
        f = _gerar(self.tmp / "av1.mp4", "libaom-av1")
        self.assertTrue(baixar.garantir_compativel(f))
        self.assertEqual(baixar.inspecionar(f)["video"], "h264")

    def test_h264_nao_mexe(self):
        f = _gerar(self.tmp / "ok.mp4", "libx264")
        antes = f.stat().st_mtime_ns
        self.assertFalse(baixar.garantir_compativel(f))
        self.assertEqual(f.stat().st_mtime_ns, antes)

    def test_so_audio_e_detectado(self):
        f = _gerar(self.tmp / "audio.mp4", None, sem_video=True)
        with self.assertRaises(baixar.SemVideo):
            baixar.garantir_compativel(f)

    def test_consertar_pasta(self):
        _gerar(self.tmp / "a.mp4", "libvpx-vp9", "libopus")
        _gerar(self.tmp / "b.mp4", "libx264")
        _gerar(self.tmp / "c.mp4", None, sem_video=True)
        status = {Path(r.link).name: r.status for r in baixar.consertar_pasta(self.tmp)}
        self.assertEqual(status, {"a.mp4": "consertado", "b.mp4": "ja_existia", "c.mp4": "erro"})


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

    def test_download_em_vp9_sai_em_h264(self):
        origem = _gerar(self.tmp / "fonte" / "reel_vp9.mp4", "libvpx-vp9", "libopus")
        r = baixar.baixar_um(origem.as_uri(), self.saida, validar=False)
        self.assertEqual(r.status, "baixado", r.erro)
        video = Path(r.arquivos[0])
        self.assertEqual(baixar.inspecionar(video)["video"], "h264")
        self.assertTrue(json.loads(video.with_suffix(".json").read_text())["convertido_para_h264"])

    def test_download_so_audio_vira_erro_explicado(self):
        origem = _gerar(self.tmp / "fonte" / "foto_com_musica.mp4", None, sem_video=True)
        r = baixar.baixar_um(origem.as_uri(), self.saida, validar=False)
        self.assertEqual(r.status, "erro")
        self.assertIn("foto", r.dica)
        self.assertEqual(list(self.saida.glob("*.mp4")), [])


if __name__ == "__main__":
    unittest.main()
