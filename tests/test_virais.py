import unittest

from agente_instagram.virais import (Reel, calcular_multiplos, gancho_da_legenda,
                                     linhas_tsv, normalizar_perfil, url_dos_reels)


def reel(perfil="fulano", views=None, curtidas=None, gancho="g", ident="1"):
    return Reel(perfil=perfil, link=f"https://www.instagram.com/reel/{ident}/", id=ident,
                views=views, curtidas=curtidas, comentarios=None, data=None, gancho=gancho)


class TestNormalizarPerfil(unittest.TestCase):
    def test_aceita_arroba_nome_e_link(self):
        for entrada in ("@Fulano", "fulano", "https://www.instagram.com/fulano/",
                        "https://instagram.com/Fulano/reels/?igsh=abc", "instagram.com/fulano/reels"):
            self.assertEqual(normalizar_perfil(entrada), "fulano", entrada)

    def test_monta_a_url_dos_reels(self):
        self.assertEqual(url_dos_reels("@Fulano"), "https://www.instagram.com/fulano/reels/")


class TestGancho(unittest.TestCase):
    def test_pega_a_primeira_linha_com_texto_sem_hashtags(self):
        legenda = "\n\nNinguém compra high ticket por desconto #vendas #mentoria\noutra linha"
        self.assertEqual(gancho_da_legenda(legenda), "Ninguém compra high ticket por desconto")

    def test_legenda_vazia_nao_quebra(self):
        self.assertEqual(gancho_da_legenda(None), "")
        self.assertEqual(gancho_da_legenda("   \n\n"), "")


class TestMultiplos(unittest.TestCase):
    def test_usa_a_mediana_do_proprio_perfil(self):
        reels = [reel(views=1000, ident="a"), reel(views=4000, ident="b"), reel(views=500, ident="c")]
        self.assertEqual(calcular_multiplos(reels), 1000)
        self.assertEqual([r.multiplo for r in reels], [1.0, 4.0, 0.5])

    def test_cai_para_curtidas_quando_nao_ha_views(self):
        reels = [reel(curtidas=100, ident="a"), reel(curtidas=300, ident="b")]
        self.assertEqual(calcular_multiplos(reels), 200)
        self.assertEqual([r.multiplo for r in reels], [0.5, 1.5])

    def test_sem_numero_nenhum_nao_inventa_base(self):
        self.assertIsNone(calcular_multiplos([reel(), reel(ident="b")]))


class TestTsv(unittest.TestCase):
    def test_cabecalho_e_colunas_do_swipe(self):
        reels = [reel(views=4000, gancho="o gancho", ident="b")]
        linhas = linhas_tsv(reels, {"fulano": 1000}, {"fulano": 52000})
        self.assertEqual(linhas[0], "account\tfollowers\tmedian\tviews\thook")
        self.assertEqual(linhas[1], "@fulano\t52000\t1000\t4000\to gancho")

    def test_seguidores_desconhecidos_ficam_em_branco(self):
        linhas = linhas_tsv([reel(views=10)], {"fulano": 10})
        self.assertEqual(linhas[1].split("\t")[1], "")


if __name__ == "__main__":
    unittest.main()
