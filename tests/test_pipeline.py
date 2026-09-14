# -*- coding: utf-8 -*-
"""
Suíte de testes automatizados do Desafio 5 — I2A2.

Cobre as quatro etapas do pipeline sem depender de rede ou de chaves de API:
  * extração de métricas do texto oficial dos avisos do INMET (Agente Coletor);
  * classificação dos eventos climáticos e da severidade (Agente Analisador);
  * cruzamento evento × apólice (Agente Decisor / regras de negócio);
  * redação da notificação personalizada (Agente Redator, motor local);
  * execução ponta a ponta em modo de demonstração.

Execução:
    python -m unittest discover -s tests -v
"""
import io
import os
import sys
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import (  # noqa: E402
    BusinessRulesAgent,
    DataCollectorAgent,
    DemoDataCollectorAgent,
    MessageGeneratorAgent,
    NotificationSimulator,
    WeatherAnalyzerAgent,
    carregar_base_segurados,
    carregar_cenarios_demo,
    executar_pipeline_proativo,
)


def clima(**kwargs):
    """Monta um pacote de dados meteorológicos no formato devolvido pelo Agente Coletor."""
    base = {
        "status": "sucesso",
        "cidade": "Curitiba",
        "temperatura": 22.0,
        "umidade": 80.0,
        "velocidade_vento_kmh": 10.0,
        "chuva_1h_mm": 0.0,
        "descricao_tempo": "sem avisos meteorológicos ativos",
        "pressao": 1013.0,
        "alerta_especial": "",
    }
    base.update(kwargs)
    return base


def segurado(**kwargs):
    """Monta um registro de segurado no formato da carteira."""
    base = {
        "id": 1,
        "nome": "Teste da Silva",
        "email": "teste@email.com",
        "telefone": "+55 11 90000-0000",
        "cidade": "Curitiba",
        "uf": "PR",
        "tipo_seguro": "Residencial",
        "detalhes_seguro": "Casa térrea com telhado de fibrocimento.",
    }
    base.update(kwargs)
    return base


class TestAgenteColetor(unittest.TestCase):
    """Etapa 1 — leitura do texto livre de riscos publicado pelo INMET."""

    def setUp(self):
        self.coletor = DataCollectorAgent()

    def test_extrai_pior_chuva_e_pior_vento(self):
        riscos = ["Chuva entre 20 e 30 mm/h", "Ventos intensos entre 40 e 60 km/h"]
        chuva, vento, granizo = self.coletor._extrair_metricas_dos_riscos(riscos)
        self.assertEqual(chuva, 30.0)
        self.assertEqual(vento, 60.0)
        self.assertFalse(granizo)

    def test_detecta_mencao_a_granizo(self):
        riscos = ["Possibilidade de queda de granizo e rajadas de 50 km/h"]
        _, vento, granizo = self.coletor._extrair_metricas_dos_riscos(riscos)
        self.assertEqual(vento, 50.0)
        self.assertTrue(granizo)

    def test_texto_sem_metricas_nao_quebra(self):
        chuva, vento, granizo = self.coletor._extrair_metricas_dos_riscos([])
        self.assertEqual((chuva, vento, granizo), (0.0, 0.0, False))

    def test_avisos_ficam_em_cache(self):
        """Uma execução deve consultar a API do INMET uma única vez."""
        self.coletor._avisos_hoje = [{"municipios": "Curitiba - PR", "id_severidade": 1}]
        self.assertIs(self.coletor._obter_avisos_hoje(), self.coletor._avisos_hoje)


class TestAgenteAnalisador(unittest.TestCase):
    """Etapa 2 — identificação automática dos eventos climáticos relevantes."""

    def setUp(self):
        self.analisador = WeatherAnalyzerAgent()

    def test_clima_estavel_nao_requer_comunicacao(self):
        resultado = self.analisador.analisar_risco(clima())
        self.assertFalse(resultado["requer_comunicacao"])
        self.assertEqual(resultado["eventos_detectados"], [])

    def test_chuva_critica_gera_alagamento(self):
        resultado = self.analisador.analisar_risco(clima(chuva_1h_mm=35.0))
        self.assertIn("Alagamento / Enxurrada", resultado["eventos_detectados"])
        self.assertEqual(resultado["nivel_severidade"], "CRITICO")

    def test_chuva_moderada_gera_chuva_forte(self):
        resultado = self.analisador.analisar_risco(clima(chuva_1h_mm=20.0))
        self.assertIn("Chuva Forte", resultado["eventos_detectados"])
        self.assertEqual(resultado["nivel_severidade"], "ALTO")

    def test_vento_acima_de_60_gera_vendaval_critico(self):
        resultado = self.analisador.analisar_risco(clima(velocidade_vento_kmh=75.0))
        self.assertIn("Ciclone / Vendaval Forte", resultado["eventos_detectados"])
        self.assertEqual(resultado["nivel_severidade"], "CRITICO")

    def test_granizo_por_alerta_especial(self):
        resultado = self.analisador.analisar_risco(clima(alerta_especial="granizo"))
        self.assertIn("Queda de Granizo", resultado["eventos_detectados"])

    def test_deslizamento_apenas_em_cidade_com_encostas(self):
        no_rio = self.analisador.analisar_risco(clima(cidade="Rio de Janeiro", chuva_1h_mm=55.0))
        self.assertIn("Risco Altíssimo de Deslizamento", no_rio["eventos_detectados"])

        em_campo_grande = self.analisador.analisar_risco(clima(cidade="Campo Grande", chuva_1h_mm=55.0))
        self.assertNotIn("Risco Altíssimo de Deslizamento", em_campo_grande["eventos_detectados"])


class TestRegrasDeNegocio(unittest.TestCase):
    """Etapa 3 — cruzamento entre o evento climático e o tipo de apólice."""

    def setUp(self):
        self.decisor = BusinessRulesAgent()
        self.analisador = WeatherAnalyzerAgent()

    def _elegiveis(self, dados_clima, carteira):
        analise = self.analisador.analisar_risco(dados_clima)
        return self.decisor.determinar_elegibilidade(analise, carteira)

    def test_sem_evento_ninguem_e_notificado(self):
        self.assertEqual(self._elegiveis(clima(), [segurado()]), [])

    def test_apenas_segurados_da_cidade_afetada(self):
        carteira = [segurado(cidade="Curitiba"), segurado(id=2, cidade="São Paulo", uf="SP")]
        elegiveis = self._elegiveis(clima(chuva_1h_mm=35.0), carteira)
        self.assertEqual([s["cidade"] for s in elegiveis], ["Curitiba"])

    def test_alagamento_notifica_residencial_e_empresarial(self):
        carteira = [segurado(tipo_seguro="Residencial"), segurado(id=2, tipo_seguro="Empresarial")]
        self.assertEqual(len(self._elegiveis(clima(chuva_1h_mm=35.0), carteira)), 2)

    def test_alagamento_so_notifica_auto_sem_garagem_coberta(self):
        com_garagem = segurado(tipo_seguro="Automóvel", detalhes_seguro="Sedan com garagem coberta.")
        sem_garagem = segurado(
            id=2, tipo_seguro="Automóvel",
            detalhes_seguro="Sedan Prata. Não possui garagem coberta no trabalho.",
        )
        elegiveis = self._elegiveis(clima(chuva_1h_mm=35.0), [com_garagem, sem_garagem])
        self.assertEqual([s["id"] for s in elegiveis], [2])

    def test_granizo_notifica_automovel(self):
        carteira = [segurado(tipo_seguro="Automóvel", detalhes_seguro="SUV - Placa ABC-1234.")]
        elegiveis = self._elegiveis(clima(alerta_especial="granizo"), carteira)
        self.assertEqual(len(elegiveis), 1)
        self.assertIn("lataria", elegiveis[0]["contexto_alerta"]["motivo_regrade_negocio"])

    def test_vendaval_notifica_todos_os_perfis(self):
        carteira = [
            segurado(tipo_seguro="Residencial"),
            segurado(id=2, tipo_seguro="Empresarial"),
            segurado(id=3, tipo_seguro="Automóvel", detalhes_seguro="Sedan com garagem coberta."),
        ]
        self.assertEqual(len(self._elegiveis(clima(velocidade_vento_kmh=75.0), carteira)), 3)

    def test_deslizamento_exige_imovel_em_area_de_encosta(self):
        em_encosta = segurado(
            cidade="Rio de Janeiro", uf="RJ", tipo_seguro="Residencial",
            detalhes_seguro="Casa em encosta no Morro do Estado.",
        )
        em_area_plana = segurado(
            id=2, cidade="Rio de Janeiro", uf="RJ", tipo_seguro="Residencial",
            detalhes_seguro="Apartamento em rua plana na Tijuca.",
        )
        elegiveis = self._elegiveis(
            clima(cidade="Rio de Janeiro", chuva_1h_mm=55.0), [em_encosta, em_area_plana]
        )
        motivos = {s["id"]: s["contexto_alerta"]["motivo_regrade_negocio"] for s in elegiveis}
        self.assertIn("evacuação preventiva", motivos[1])
        self.assertNotIn("evacuação preventiva", motivos[2])

    def test_contexto_do_alerta_e_anexado_ao_segurado(self):
        elegiveis = self._elegiveis(clima(chuva_1h_mm=35.0), [segurado()])
        contexto = elegiveis[0]["contexto_alerta"]
        self.assertEqual(contexto["severidade"], "CRITICO")
        self.assertIn("Alagamento / Enxurrada", contexto["eventos"])
        self.assertEqual(contexto["detalhes_clima"]["chuva"], 35.0)


class TestAgenteRedator(unittest.TestCase):
    """Etapa 4 — geração automática da mensagem personalizada."""

    def setUp(self):
        self.redator = MessageGeneratorAgent(api_provider="simulation")
        self.decisor = BusinessRulesAgent()
        self.analisador = WeatherAnalyzerAgent()

    def _mensagem_para(self, perfil, dados_clima=None):
        analise = self.analisador.analisar_risco(dados_clima or clima(chuva_1h_mm=35.0))
        elegiveis = self.decisor.determinar_elegibilidade(analise, [perfil])
        return self.redator.gerar_comunicacao_preventiva(elegiveis[0])

    def test_mensagem_e_personalizada_com_nome_e_cidade(self):
        mensagem = self._mensagem_para(segurado(nome="Helena Moreira", cidade="Curitiba"))
        self.assertIn("Helena Moreira", mensagem)
        self.assertIn("Curitiba", mensagem)

    def test_mensagem_traz_tres_recomendacoes_preventivas(self):
        mensagem = self._mensagem_para(segurado())
        self.assertEqual(mensagem.count("🔹"), 3)

    def test_recomendacoes_mudam_conforme_o_tipo_de_seguro(self):
        residencial = self._mensagem_para(segurado(tipo_seguro="Residencial"))
        automovel = self._mensagem_para(
            segurado(tipo_seguro="Automóvel", detalhes_seguro="Sedan. Não possui garagem coberta.")
        )
        empresarial = self._mensagem_para(segurado(tipo_seguro="Empresarial"))
        self.assertIn("calhas", residencial)
        self.assertIn("estacionar", automovel)
        self.assertIn("estoques", empresarial)
        self.assertNotEqual(residencial, automovel)
        self.assertNotEqual(automovel, empresarial)

    def test_fallback_do_llm_preserva_a_personalizacao(self):
        """Se a chamada ao LLM falhar, a mensagem local ainda deve citar o segurado."""
        redator = MessageGeneratorAgent(api_provider="simulation")
        analise = self.analisador.analisar_risco(clima(chuva_1h_mm=35.0))
        elegivel = self.decisor.determinar_elegibilidade(analise, [segurado(nome="Otávio Brandão")])[0]
        mensagem = redator._chamar_openai("sistema", "usuário", elegivel)  # sem chave -> cai no local
        self.assertIn("Otávio Brandão", mensagem)

    def test_provider_auto_sem_chave_usa_gerador_local(self):
        chaves = {k: os.environ.pop(k, None) for k in ("OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY")}
        try:
            self.assertEqual(MessageGeneratorAgent(api_provider="auto").api_provider, "simulation")
        finally:
            for chave, valor in chaves.items():
                if valor is not None:
                    os.environ[chave] = valor


class TestSimuladorDeEnvio(unittest.TestCase):
    """Etapa 5 — simulação do disparo multicanal."""

    def test_envio_retorna_registro_completo(self):
        analise = WeatherAnalyzerAgent().analisar_risco(clima(chuva_1h_mm=35.0))
        elegivel = BusinessRulesAgent().determinar_elegibilidade(analise, [segurado()])[0]
        with redirect_stdout(io.StringIO()) as saida:
            registro = NotificationSimulator().enviar(elegivel, "mensagem de teste", "template-local")
        self.assertIn("DISPARO DE NOTIFICAÇÃO PROATIVA", saida.getvalue())
        self.assertEqual(registro["segurado"], "Teste da Silva")
        self.assertEqual(registro["cidade"], "Curitiba - PR")
        self.assertEqual(registro["motor_de_geracao"], "template-local")


class TestBasesDeDados(unittest.TestCase):
    """Integridade dos arquivos de dados versionados no repositório."""

    def test_carteira_de_segurados_esta_integra(self):
        carteira = carregar_base_segurados()
        self.assertGreater(len(carteira), 0)
        obrigatorios = {"nome", "email", "telefone", "cidade", "uf", "tipo_seguro", "detalhes_seguro"}
        for registro in carteira:
            self.assertTrue(obrigatorios.issubset(registro.keys()), registro)
            self.assertIn(registro["tipo_seguro"], {"Residencial", "Empresarial", "Automóvel"})

    def test_cenarios_de_demonstracao_estao_integros(self):
        demo = carregar_cenarios_demo()
        self.assertGreaterEqual(len(demo["cenarios"]), 5)
        self.assertGreaterEqual(len(demo["segurados"]), 5)
        for chave in demo["cenarios"]:
            self.assertRegex(chave, r"^.+ - [A-Z]{2}$")


class TestPipelinePontaAPonta(unittest.TestCase):
    """Fluxo completo, do dado climático à notificação, sem acesso à rede."""

    def test_modo_demo_gera_notificacoes_para_todos_os_perfis(self):
        with redirect_stdout(io.StringIO()):
            resumo = executar_pipeline_proativo(provider="simulation", modo_demo=True)

        self.assertEqual(resumo["modo"], "demonstracao")
        self.assertGreaterEqual(resumo["total_notificacoes"], 5)

        perfis = {n["tipo_seguro"] for n in resumo["notificacoes"]}
        self.assertEqual(perfis, {"Residencial", "Empresarial", "Automóvel"})

        eventos = {evento for n in resumo["notificacoes"] for evento in n["eventos"]}
        self.assertIn("Alagamento / Enxurrada", eventos)
        self.assertIn("Queda de Granizo", eventos)
        self.assertIn("Ciclone / Vendaval Forte", eventos)
        self.assertIn("Risco Altíssimo de Deslizamento", eventos)

    def test_cidade_sem_evento_nao_gera_notificacao(self):
        with redirect_stdout(io.StringIO()):
            resumo = executar_pipeline_proativo(
                provider="simulation", modo_demo=True, cidade_filtro="Fortaleza"
            )
        self.assertEqual(resumo["cidades_monitoradas"], 1)
        self.assertEqual(resumo["total_notificacoes"], 0)

    def test_coletor_de_demo_respeita_o_cenario_configurado(self):
        cenarios = carregar_cenarios_demo()["cenarios"]
        dados = DemoDataCollectorAgent(cenarios).coletar_dados("Curitiba", "PR")
        self.assertEqual(dados["alerta_especial"], "granizo")
        self.assertEqual(dados["cidade"], "Curitiba")


if __name__ == "__main__":
    unittest.main(verbosity=2)
