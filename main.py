"""
Ferramenta Inteligente para Comunicação Proativa com o Segurado — Desafio 5 (I2A2).

Pipeline multiagente que consulta os avisos meteorológicos oficiais do INMET, identifica
eventos climáticos de risco, cruza esses eventos com a carteira de segurados e redige
(via LLM ou gerador local) notificações preventivas personalizadas.

Uso:
    python main.py                     # execução padrão (dados reais do INMET)
    python main.py --demo              # cenários controlados (demonstração do fluxo completo)
    python main.py --provider gemini   # força a geração das mensagens com LLM
    python main.py --salvar            # grava as notificações geradas em saida/*.json
"""

import argparse
import json
import logging
import os
import re
import sys
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import requests
from dotenv import load_dotenv

# Os emojis das notificações quebram a execução em terminais cp1252 (padrão do Windows)
# e ao redirecionar a saída para arquivo. Forçar UTF-8 evita o UnicodeEncodeError.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

load_dotenv()  # carrega variáveis do arquivo .env para o ambiente

# Configuração do Logging para visualização clara no terminal
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [%(levelname)s] - %(name)s: %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("I2A2-Desafio5")

# As bibliotecas HTTP e os SDKs de LLM emitem um log por requisição, o que polui
# a leitura do fluxo dos agentes. Só interessam os avisos e erros delas.
for _biblioteca in ("httpx", "httpcore", "urllib3", "google_genai", "openai"):
    logging.getLogger(_biblioteca).setLevel(logging.WARNING)

# Caminhos resolvidos a partir da pasta do projeto, e não do diretório de trabalho.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ARQUIVO_SEGURADOS = os.path.join(BASE_DIR, "segurados.json")
ARQUIVO_CENARIOS_DEMO = os.path.join(BASE_DIR, "cenarios_demo.json")
DIR_SAIDA = os.path.join(BASE_DIR, "saida")

# Regra 4: municípios da carteira com ocupação relevante em encostas, onde chuva volumosa
# configura risco geotécnico (deslizamento) além do risco de alagamento.
CIDADES_RISCO_DESLIZAMENTO = {
    "rio de janeiro", "belo horizonte", "salvador", "recife",
    "vitória", "florianópolis", "são paulo", "porto alegre",
}

# Termos usados para identificar, no cadastro do segurado, imóveis em área de encosta.
TERMOS_AREA_ENCOSTA = ("encosta", "morro", "ladeira", "serra", "aclive", "declive")

# =====================================================================
# GERENCIADOR DA BASE DE DADOS DE SEGURADOS
# =====================================================================
def carregar_base_segurados() -> List[Dict[str, Any]]:
    """
    Carrega a base de dados dos segurados a partir de um arquivo JSON externo.
    Se o arquivo não existir, cria um arquivo padrão (seeding) com um registro mínimo
    para garantir que o MVP funcione perfeitamente out-of-the-box.
    """
    dados_padrao = [
        {
            "id": 1,
            "nome": "Carlos Silva",
            "email": "carlos.silva@email.com",
            "telefone": "+55 11 99999-1111",
            "cidade": "São Paulo",
            "uf": "SP",
            "tipo_seguro": "Automóvel",
            "detalhes_seguro": "Sedan Prata - Placa ABC-1234. Não possui garagem coberta no trabalho."
        }
    ]

    if not os.path.exists(ARQUIVO_SEGURADOS):
        try:
            with open(ARQUIVO_SEGURADOS, "w", encoding="utf-8") as f:
                json.dump(dados_padrao, f, ensure_ascii=False, indent=2)
            logger.info(f"[Database] Arquivo '{ARQUIVO_SEGURADOS}' não encontrado. Criado arquivo padrão de exemplo.")
            return dados_padrao
        except Exception as e:
            logger.error(f"[Database] Falha ao criar arquivo de segurados padrão: {str(e)}")
            return dados_padrao

    try:
        with open(ARQUIVO_SEGURADOS, "r", encoding="utf-8") as f:
            segurados = json.load(f)
        logger.info(f"[Database] Base de segurados carregada com sucesso a partir de '{ARQUIVO_SEGURADOS}' ({len(segurados)} registros).")
        return segurados
    except Exception as e:
        logger.error(f"[Database] Erro ao carregar '{ARQUIVO_SEGURADOS}': {str(e)}. Utilizando dados em memória como fallback.")
        return dados_padrao


# =====================================================================
# AGENTE 1: COLETOR DE DADOS METEOROLÓGICOS (DataCollectorAgent)
# =====================================================================
class DataCollectorAgent:
    """
    Agente responsável por buscar informações de fontes meteorológicas externas.
    Consulta em tempo real a API pública de avisos ativos do INMET (Instituto Nacional
    de Meteorologia), fonte oficial usada pela Defesa Civil e pela imprensa.
    """
    URL_AVISOS_INMET = "https://apiprevmet3.inmet.gov.br/avisos/ativos"
    TIMEOUT_SEGUNDOS = 15

    def __init__(self):
        self.name = "Agente_Coletor"
        # A API devolve todos os avisos vigentes do país em uma única resposta; o cache
        # reduz a execução a uma requisição, em vez de uma por cidade da carteira.
        self._avisos_hoje: Optional[List[Dict[str, Any]]] = None
        logger.info(f"[{self.name}] Inicializado em modo TEMPO REAL (API pública de avisos do INMET).")

    def coletar_dados(self, cidade: str, uf: str) -> Dict[str, Any]:
        """
        Coleta o aviso meteorológico oficial de maior severidade vigente hoje para a cidade,
        consultando diretamente a API pública de avisos ativos do INMET.
        """
        aviso = self._consultar_avisos_inmet(cidade, uf)

        if not aviso:
            logger.info(f"[{self.name}] Nenhum aviso ativo do INMET para {cidade}. Clima considerado estável.")
            return {
                "status": "sucesso",
                "cidade": cidade,
                "temperatura": 24.0,
                "umidade": 60.0,
                "velocidade_vento_kmh": 10.0,
                "chuva_1h_mm": 0.0,
                "descricao_tempo": "sem avisos meteorológicos ativos",
                "pressao": 1013.0,
                "alerta_especial": ""
            }

        chuva_mm, vento_kmh, tem_granizo = self._extrair_metricas_dos_riscos(aviso.get("riscos", []))
        return {
            "status": "sucesso",
            "cidade": cidade,
            "temperatura": 24.0,
            "umidade": 85.0,
            "velocidade_vento_kmh": vento_kmh,
            "chuva_1h_mm": chuva_mm,
            "descricao_tempo": f"Aviso oficial INMET: {aviso.get('descricao')} ({aviso.get('severidade')})",
            "pressao": 1009.0,
            "alerta_especial": "granizo" if tem_granizo else ""
        }

    def _consultar_avisos_inmet(self, cidade: str, uf: str) -> Optional[Dict[str, Any]]:
        """
        Consulta a API pública de avisos ativos do INMET e retorna o aviso de maior
        severidade vigente hoje que cubra o município informado.
        """
        termo_busca = f"{cidade} - {uf}"
        avisos_relevantes = [
            aviso for aviso in self._obter_avisos_hoje()
            if termo_busca in aviso.get("municipios", "")
        ]
        if not avisos_relevantes:
            return None

        pior_aviso = max(avisos_relevantes, key=lambda a: a.get("id_severidade", 0))
        logger.info(
            f"[{self.name}] Aviso oficial do INMET encontrado para {cidade}: "
            f"{pior_aviso.get('severidade')} - {pior_aviso.get('descricao')}"
        )
        return {
            "severidade": pior_aviso.get("severidade"),
            "descricao": pior_aviso.get("descricao"),
            "riscos": pior_aviso.get("riscos", []),
        }

    def _obter_avisos_hoje(self) -> List[Dict[str, Any]]:
        """
        Baixa uma única vez por execução a lista de avisos vigentes hoje no país e a mantém
        em cache, evitando repetir a mesma requisição para cada cidade da carteira.
        """
        if self._avisos_hoje is not None:
            return self._avisos_hoje

        try:
            response = requests.get(self.URL_AVISOS_INMET, timeout=self.TIMEOUT_SEGUNDOS)
            if response.status_code != 200:
                logger.error(f"[{self.name}] Erro na chamada à API do INMET ({response.status_code}).")
                self._avisos_hoje = []
                return self._avisos_hoje
            self._avisos_hoje = response.json().get("hoje", [])
            logger.info(
                f"[{self.name}] {len(self._avisos_hoje)} aviso(s) meteorológico(s) vigente(s) "
                f"hoje recuperado(s) do INMET em uma única requisição."
            )
        except Exception as e:
            logger.error(f"[{self.name}] Falha ao consultar a API do INMET: {str(e)}")
            self._avisos_hoje = []
        return self._avisos_hoje

    def _extrair_metricas_dos_riscos(self, riscos: List[str]) -> Tuple[float, float, bool]:
        """
        Extrai estimativas conservadoras (piores valores) de chuva e vento a partir do
        texto oficial de riscos do INMET (ex: "Chuva entre 20 e 30 mm/h... ventos (40-60 km/h)").
        """
        texto = " ".join(riscos)
        valores_chuva = [float(v) for v in re.findall(r"(\d+)\s*mm/h", texto)]
        valores_vento = [float(v) for v in re.findall(r"(\d+)\s*km/h", texto)]
        chuva_mm = max(valores_chuva) if valores_chuva else 0.0
        vento_kmh = max(valores_vento) if valores_vento else 0.0
        tem_granizo = "granizo" in texto.lower()
        return chuva_mm, vento_kmh, tem_granizo


# =====================================================================
# VARIANTE DO AGENTE 1 PARA DEMONSTRAÇÃO (DemoDataCollectorAgent)
# =====================================================================
class DemoDataCollectorAgent(DataCollectorAgent):
    """
    Variante do Agente Coletor usada no modo de demonstração (`python main.py --demo`).
    Em vez de consultar o INMET, devolve cenários climáticos controlados descritos em
    `cenarios_demo.json`. Isso garante que o fluxo completo — e os diferentes tipos de
    mensagem — possa ser demonstrado mesmo em um dia sem avisos ativos no país, sem
    alterar uma única linha dos demais agentes do pipeline.
    """

    def __init__(self, cenarios: Dict[str, Dict[str, Any]]):
        self.name = "Agente_Coletor_Demo"
        self._avisos_hoje = []
        self.cenarios = cenarios
        logger.info(
            f"[{self.name}] Inicializado em modo DEMONSTRAÇÃO "
            f"({len(cenarios)} cenários climáticos controlados)."
        )

    def coletar_dados(self, cidade: str, uf: str) -> Dict[str, Any]:
        cenario = self.cenarios.get(f"{cidade} - {uf}")
        if not cenario:
            logger.info(f"[{self.name}] Nenhum cenário controlado para {cidade}. Clima considerado estável.")
            return {
                "status": "sucesso",
                "cidade": cidade,
                "temperatura": 24.0,
                "umidade": 60.0,
                "velocidade_vento_kmh": 10.0,
                "chuva_1h_mm": 0.0,
                "descricao_tempo": "sem avisos meteorológicos ativos",
                "pressao": 1013.0,
                "alerta_especial": "",
            }

        logger.info(
            f"[{self.name}] Cenário '{cenario.get('nome_cenario', cidade)}' carregado para {cidade} - {uf}."
        )
        dados = {chave: valor for chave, valor in cenario.items() if chave != "nome_cenario"}
        dados["status"] = "sucesso"
        dados["cidade"] = cidade
        return dados


# =====================================================================
# AGENTE 2: ANALISADOR DE EVENTOS CLIMÁTICOS (WeatherAnalyzerAgent)
# =====================================================================
class WeatherAnalyzerAgent:
    """
    Agente responsável por interpretar as variáveis brutas do clima
    e identificar eventos climáticos de risco relevantes para seguros.
    """
    def __init__(self):
        self.name = "Agente_Analisador"

    def analisar_risco(self, dados_clima: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analisa os limites meteorológicos para classificar os riscos de sinistro.
        """
        if dados_clima.get("status") == "erro":
            return {"cidade": dados_clima["cidade"], "requer_comunicacao": False}

        logger.info(f"[{self.name}] Analisando dados meteorológicos de {dados_clima['cidade']}...")
        
        chuva = dados_clima.get("chuva_1h_mm", 0.0)
        vento = dados_clima.get("velocidade_vento_kmh", 0.0)
        alerta_especial = dados_clima.get("alerta_especial", "")
        descricao = dados_clima.get("descricao_tempo", "").lower()
        
        eventos_identificados = []
        nivel_severidade = "BAIXO"  # Níveis: BAIXO, MEDIO, ALTO, CRITICO

        # Regra 1: Alagamento / Enchente (Chuvas acima de 30mm/h)
        if chuva >= 30.0:
            eventos_identificados.append("Alagamento / Enxurrada")
            nivel_severidade = "CRITICO"
        elif chuva >= 15.0:
            eventos_identificados.append("Chuva Forte")
            nivel_severidade = "ALTO"

        # Regra 2: Vendaval / Tempestades (Vento acima de 50 km/h)
        if vento >= 60.0:
            eventos_identificados.append("Ciclone / Vendaval Forte")
            nivel_severidade = "CRITICO"
        elif vento >= 40.0:
            eventos_identificados.append("Ventos Fortes")
            nivel_severidade = "ALTO"

        # Regra 3: Queda de Granizo (Detectado por alerta especial)
        if "granizo" in descricao or alerta_especial == "granizo":
            eventos_identificados.append("Queda de Granizo")
            nivel_severidade = "ALTO"

        # Regra 4: Deslizamento de Terra (chuva volumosa em municípios com ocupação em encostas)
        if chuva >= 40.0 and dados_clima["cidade"].strip().lower() in CIDADES_RISCO_DESLIZAMENTO:
            eventos_identificados.append("Risco Altíssimo de Deslizamento")
            nivel_severidade = "CRITICO"

        # Compila a análise técnica
        analise_resultado = {
            "cidade": dados_clima["cidade"],
            "eventos_detectados": eventos_identificados,
            "nivel_severidade": nivel_severidade,
            "temperatura": dados_clima["temperatura"],
            "velocidade_vento_kmh": vento,
            "chuva_1h_mm": chuva,
            "descricao_original": descricao,
            "requer_comunicacao": len(eventos_identificados) > 0
        }
        
        if analise_resultado["requer_comunicacao"]:
            logger.warning(
                f"[{self.name}] RISCO IDENTIFICADO em {dados_clima['cidade']}! "
                f"Eventos: {eventos_identificados} | Severidade: {nivel_severidade}"
            )
        else:
            logger.info(f"[{self.name}] Clima está sob controle em {dados_clima['cidade']}. Sem riscos iminentes.")
            
        return analise_resultado


# =====================================================================
# AGENTE 3: DECISOR DE REGRAS DE NEGÓCIO (BusinessRulesAgent)
# =====================================================================
class BusinessRulesAgent:
    """
    Agente responsável por casar os riscos detectados pelo Analisador
    com a carteira de segurados elegíveis, aplicando regras de negócio e de apólice.
    """
    def __init__(self):
        self.name = "Agente_Decisor"

    def determinar_elegibilidade(
        self, analise_clima: Dict[str, Any], lista_segurados: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Verifica quais segurados moram na área de risco e se o tipo de apólice deles
        justifica o envio da comunicação preventiva.
        """
        if not analise_clima.get("requer_comunicacao"):
            return []

        logger.info(f"[{self.name}] Aplicando regras de apólice para a cidade: {analise_clima['cidade']}...")
        
        segurados_afetados = []
        eventos = analise_clima["eventos_detectados"]

        for segurado in lista_segurados:
            # Regra Geográfica: O segurado reside na cidade do evento meteorológico?
            if segurado["cidade"].lower() != analise_clima["cidade"].lower():
                continue

            # Um mesmo aviso pode disparar mais de uma regra (vendaval e granizo, por exemplo);
            # os motivos são acumulados para que a mensagem cite o quadro completo de risco.
            motivos_elegibilidade: List[str] = []

            # Regras Cruzadas de Apólice e Evento:
            # 1. Alagamento -> Afeta principalmente Seguro Residencial ou Empresarial de rua
            if "Alagamento / Enxurrada" in eventos:
                if segurado["tipo_seguro"] in ["Residencial", "Empresarial"]:
                    motivos_elegibilidade.append(
                        "Risco de inundação do imóvel segurado devido a volume de chuva crítico."
                    )
                elif segurado["tipo_seguro"] == "Automóvel" and "não possui garagem coberta" in segurado["detalhes_seguro"].lower():
                    motivos_elegibilidade.append(
                        "Risco de alagamento do veículo que estaciona em via pública."
                    )

            # 2. Queda de Granizo -> Afeta gravemente apólices de Automóvel e Residencial (telhados)
            if "Queda de Granizo" in eventos:
                if segurado["tipo_seguro"] == "Automóvel":
                    motivos_elegibilidade.append(
                        "Risco de avarias na lataria e vidros do veículo segurado."
                    )
                elif segurado["tipo_seguro"] == "Residencial":
                    motivos_elegibilidade.append(
                        "Risco de quebra de telhados e vidraças do imóvel."
                    )

            # 3. Ventos Fortes ou Ciclone -> Afeta Residencial, Empresarial e Automóvel (queda de árvores)
            if "Ciclone / Vendaval Forte" in eventos or "Ventos Fortes" in eventos:
                if segurado["tipo_seguro"] in ["Residencial", "Empresarial"]:
                    motivos_elegibilidade.append(
                        "Risco de destelhamento e danos estruturais no imóvel."
                    )
                elif segurado["tipo_seguro"] == "Automóvel":
                    motivos_elegibilidade.append(
                        "Alto risco de queda de galhos/árvores sobre o veículo estacionado."
                    )

            # 4. Deslizamento -> Altamente crítico para imóveis em encostas
            if "Risco Altíssimo de Deslizamento" in eventos:
                detalhes = segurado.get("detalhes_seguro", "").lower()
                if segurado["tipo_seguro"] in ["Residencial", "Empresarial"] and any(
                    termo in detalhes for termo in TERMOS_AREA_ENCOSTA
                ):
                    motivos_elegibilidade.append(
                        "Alerta máximo de evacuação preventiva e proteção de vidas."
                    )

            if motivos_elegibilidade:
                # Remove repetições preservando a ordem em que as regras dispararam.
                motivo_elegibilidade = " ".join(dict.fromkeys(motivos_elegibilidade))

                # Payload unificado: cadastro do segurado + contexto do evento climático.
                segurado_notificar = segurado.copy()
                segurado_notificar["contexto_alerta"] = {
                    "eventos": eventos,
                    "severidade": analise_clima["nivel_severidade"],
                    "motivo_regrade_negocio": motivo_elegibilidade,
                    "detalhes_clima": {
                        "chuva": analise_clima["chuva_1h_mm"],
                        "vento": analise_clima["velocidade_vento_kmh"],
                        "temperatura": analise_clima["temperatura"]
                    }
                }
                segurados_afetados.append(segurado_notificar)
                logger.info(
                    f"[{self.name}] Segurado ELEGÍVEL encontrado! Nome: {segurado['nome']} | "
                    f"Seguro: {segurado['tipo_seguro']} | Motivo: {motivo_elegibilidade}"
                )

        return segurados_afetados


# =====================================================================
# AGENTE 4: GERADOR DE MENSAGENS COM IA (MessageGeneratorAgent)
# =====================================================================
class MessageGeneratorAgent:
    """
    Agente responsável por redigir a mensagem de comunicação personalizada.
    Utiliza API real de IA Generativa se configurada, ou um gerador cognitivo
    de alta fidelidade baseado em templates enriquecidos por contexto caso offline.
    """
    # Modelos de cada provedor, sobrescritíveis por OPENAI_MODEL / GEMINI_MODEL no .env.
    MODELOS_OPENAI = ("gpt-4o-mini",)
    MODELOS_GEMINI = ("gemini-3.6-flash", "gemini-flash-latest")

    # Espera, em segundos, antes de repetir a chamada quando a API responde 429 (cota por minuto).
    ESPERAS_APOS_LIMITE = (5,)

    # Após esta sequência de falhas o provedor é considerado indisponível, e o restante da
    # execução usa o gerador local em vez de insistir em chamadas fadadas a falhar.
    FALHAS_ATE_DESLIGAR_LLM = 3

    def __init__(self, api_provider: str = "auto"):
        self.name = "Agente_Redator_IA"

        # As credenciais vêm exclusivamente do ambiente (.env), nunca do código.
        self.openai_key = os.getenv("OPENAI_API_KEY")
        self.gemini_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        self.modelo_em_uso = "template-local"
        # Motor que de fato redigiu a última mensagem. Difere de `modelo_em_uso` sempre que
        # o LLM falha e o gerador local assume, e é o valor reportado ao segurado.
        self.ultimo_motor = "template-local"
        self.motores_utilizados: Dict[str, int] = {}
        self._falhas_consecutivas = 0
        self._llm_desligado = False

        # Em "auto" a IA generativa é usada sempre que houver credencial configurada;
        # o gerador local entra apenas quando nenhuma chave está disponível.
        if api_provider == "auto":
            if self.gemini_key:
                api_provider = "gemini"
            elif self.openai_key:
                api_provider = "openai"
            else:
                api_provider = "simulation"

        self.api_provider = api_provider  # "openai", "gemini" ou "simulation"

        if self.api_provider == "openai" and self.openai_key:
            self.modelo_em_uso = os.getenv("OPENAI_MODEL", self.MODELOS_OPENAI[0])
            logger.info(f"[{self.name}] Geração de mensagens via OpenAI ({self.modelo_em_uso}).")
        elif self.api_provider == "gemini" and self.gemini_key:
            self.modelo_em_uso = os.getenv("GEMINI_MODEL", self.MODELOS_GEMINI[0])
            logger.info(f"[{self.name}] Geração de mensagens via Google Gemini ({self.modelo_em_uso}).")
        else:
            if self.api_provider in ("openai", "gemini"):
                logger.warning(
                    f"[{self.name}] Provedor '{self.api_provider}' solicitado, mas nenhuma chave de API "
                    f"foi encontrada no ambiente/.env. Revertendo para o gerador local."
                )
            self.api_provider = "simulation"
            logger.info(f"[{self.name}] Utilizando motor cognitivo interno de simulação (Local Template Generator).")

    def _registrar_motor(self, motor: str, texto: str) -> str:
        """Marca qual motor produziu o texto, para que a origem seja reportada corretamente."""
        if motor != "template-local":
            self._falhas_consecutivas = 0
        self.ultimo_motor = motor
        self.motores_utilizados[motor] = self.motores_utilizados.get(motor, 0) + 1
        return texto

    def gerar_comunicacao_preventiva(self, dados_elegibilidade: Dict[str, Any]) -> str:
        """
        Monta um prompt estruturado de IA para criar uma mensagem proativa, empática,
        clara e focada em prevenção de danos.
        """
        nome = dados_elegibilidade["nome"]
        tipo_seguro = dados_elegibilidade["tipo_seguro"]
        detalhes_seguro = dados_elegibilidade["detalhes_seguro"]
        cidade = dados_elegibilidade["cidade"]
        
        alerta = dados_elegibilidade["contexto_alerta"]
        eventos_clima = ", ".join(alerta["eventos"])
        severidade = alerta["severidade"]
        motivo = alerta["motivo_regrade_negocio"]
        chuva = alerta["detalhes_clima"]["chuva"]
        vento = alerta["detalhes_clima"]["vento"]

        # Persona e diretrizes de escrita aplicadas ao modelo.
        system_prompt = (
            "Você é a inteligência proativa de uma Seguradora de alta confiabilidade. "
            "Seu tom deve ser empático, urgente mas não alarmista, e focado em segurança física e material. "
            "Gere uma mensagem curta, estruturada em tópicos curtos de prevenção, direta e personalizada, "
            "evitando termos burocráticos ou robóticos."
        )

        user_content = (
            f"Gere uma notificação urgente para o cliente {nome}, morador de {cidade}. "
            f"Identificamos o seguinte risco climático imediato: {eventos_clima} (Severidade: {severidade}). "
            f"O motivo da preocupação para a apólice dele ({tipo_seguro} - {detalhes_seguro}) é: {motivo}. "
            f"Dados de medição: Chuva de {chuva}mm/h, ventos de {vento}km/h. "
            "Inclua 3 passos curtos de prevenção específicos para o tipo de seguro dele e informe que a "
            "seguradora está ao seu lado caso precise acionar assistência 24h."
        )

        if self._llm_desligado or self.api_provider == "simulation":
            return self._gerar_simulacao_heuristica(dados_elegibilidade)
        if self.api_provider == "openai":
            return self._chamar_openai(system_prompt, user_content, dados_elegibilidade)
        return self._chamar_gemini(system_prompt, user_content, dados_elegibilidade)

    def _chamar_openai(
        self, system_prompt: str, user_prompt: str, dados: Optional[Dict[str, Any]] = None
    ) -> str:
        """Chamada real utilizando a biblioteca oficial 'openai'."""
        try:
            from openai import OpenAI
            client = OpenAI(api_key=self.openai_key)
            response = client.chat.completions.create(
                model=self.modelo_em_uso,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.7,
                max_tokens=400
            )
            return self._registrar_motor(self.modelo_em_uso, response.choices[0].message.content.strip())
        except Exception as e:
            logger.error(
                f"[{self.name}] Falha ao gerar a mensagem via OpenAI: {str(e)}. "
                f"Usando o gerador local para não deixar o segurado sem comunicação."
            )
            return self._gerar_simulacao_heuristica(dados)

    def _chamar_gemini(
        self, system_prompt: str, user_prompt: str, dados: Optional[Dict[str, Any]] = None
    ) -> str:
        """Gera a mensagem com o Google Gemini através do SDK oficial google-genai."""
        try:
            from google import genai
            from google.genai import types
        except ImportError as e:
            logger.error(f"[{self.name}] Biblioteca 'google-genai' indisponível ({e}). Usando o gerador local.")
            return self._gerar_simulacao_heuristica(dados)

        cliente = genai.Client(api_key=self.gemini_key)
        configuracao = types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=0.7,
            max_output_tokens=900,
            # Sem orçamento de raciocínio: a notificação é curta e o limite de saída
            # precisa ser integralmente destinado ao texto enviado ao segurado.
            thinking_config=types.ThinkingConfig(thinking_budget=0),
            # O agente não expõe ferramentas ao modelo; desligar a chamada automática
            # de funções evita uma ida e volta desnecessária a cada requisição.
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )

        # Percorre os modelos suportados: o primeiro disponível na conta responde.
        candidatos = [self.modelo_em_uso] + [m for m in self.MODELOS_GEMINI if m != self.modelo_em_uso]
        ultimo_erro = None
        for modelo in candidatos:
            for tentativa, espera in enumerate((0,) + self.ESPERAS_APOS_LIMITE):
                if espera:
                    time.sleep(espera)
                try:
                    resposta = cliente.models.generate_content(
                        model=modelo, contents=user_prompt, config=configuracao
                    )
                    texto = (resposta.text or "").strip()
                    if not texto:
                        raise ValueError("resposta vazia do modelo")
                    if str(getattr(resposta.candidates[0], "finish_reason", "STOP")).endswith("MAX_TOKENS"):
                        raise ValueError("resposta truncada pelo limite de tokens")
                    if modelo != self.modelo_em_uso:
                        logger.warning(f"[{self.name}] Modelo '{self.modelo_em_uso}' indisponível; usando '{modelo}'.")
                        self.modelo_em_uso = modelo
                    return self._registrar_motor(modelo, texto)
                except Exception as e:
                    ultimo_erro = e
                    # 429 é limite de requisições por minuto do plano gratuito: vale esperar
                    # e tentar de novo no mesmo modelo. Os demais erros são definitivos.
                    if "429" not in str(e) and "RESOURCE_EXHAUSTED" not in str(e):
                        break
                    if tentativa < len(self.ESPERAS_APOS_LIMITE):
                        logger.info(
                            f"[{self.name}] Limite de requisições atingido em '{modelo}'. "
                            f"Nova tentativa em {self.ESPERAS_APOS_LIMITE[tentativa]}s."
                        )

        logger.error(
            f"[{self.name}] Falha ao gerar a mensagem via Gemini: {str(ultimo_erro)}. "
            f"Usando o gerador local para não deixar o segurado sem comunicação."
        )
        return self._gerar_simulacao_heuristica(dados)

        genai.configure(api_key=self.gemini_key)
        prompt_completo = f"{system_prompt}\n\nInstrução:\n{user_prompt}"

        # Tenta o modelo configurado e, se ele não estiver habilitado na conta, os demais
        # modelos suportados — evitando que a entrega dependa de um nome de modelo específico.
        candidatos = [self.modelo_em_uso] + [m for m in self.MODELOS_GEMINI if m != self.modelo_em_uso]
        ultimo_erro = None
        for modelo in candidatos:
            try:
                resposta = genai.GenerativeModel(modelo).generate_content(prompt_completo)
                if modelo != self.modelo_em_uso:
                    logger.warning(
                        f"[{self.name}] Modelo '{self.modelo_em_uso}' indisponível nesta conta; "
                        f"utilizando '{modelo}'."
                    )
                    self.modelo_em_uso = modelo
                return resposta.text.strip()
            except Exception as e:
                ultimo_erro = e

        logger.error(
            f"[{self.name}] Falha ao gerar a mensagem via Gemini: {str(ultimo_erro)}. "
            f"Revertendo para o gerador local (a comunicação nunca deixa de ser enviada)."
        )
        return self._gerar_simulacao_heuristica(dados)

    def _registrar_falha_do_llm(self) -> None:
        """Abre o disjuntor após falhas seguidas no provedor de IA."""
        self._falhas_consecutivas += 1
        if not self._llm_desligado and self._falhas_consecutivas >= self.FALHAS_ATE_DESLIGAR_LLM:
            self._llm_desligado = True
            logger.warning(
                f"[{self.name}] {self._falhas_consecutivas} falhas consecutivas no provedor "
                f"'{self.api_provider}'. As mensagens restantes sairão do gerador local."
            )

    def _gerar_simulacao_heuristica(self, dados: Dict[str, Any]) -> str:
        """
        Gerador de mensagens local, rico e de alta fidelidade que simula perfeitamente
        o comportamento e o tom de uma IA generativa especializada em prevenção.
        """
        self.ultimo_motor = "template-local"
        if self.api_provider != "simulation":
            self._registrar_falha_do_llm()

        if not dados:
            return (
                "⚠️ [ALERTA DE PREVENÇÃO] Olá! Identificamos condições severas na sua área. "
                "Para sua segurança, estacione seu carro em local seguro e feche bem as janelas de casa. "
                "Caso precise de assistência emergencial, acione nosso canal 24h pelo app ou telefone."
            )

        nome = dados["nome"]
        tipo = dados["tipo_seguro"]
        cidade = dados["cidade"]
        motivo = dados["contexto_alerta"]["motivo_regrade_negocio"]
        eventos = dados["contexto_alerta"]["eventos"]
        evento_principal = eventos[0] if eventos else "Mudança Climática"

        mensagem = (
            f"🚨 *ALERTA DE PREVENÇÃO PROATIVA - {evento_principal.upper()}*\n\n"
            f"Olá, *{nome}*!\n"
            f"Nossos sistemas de monitoramento identificaram risco iminente de *{', '.join(eventos)}* na região de *{cidade}*.\n"
            f"Identificamos que sua apólice de *Seguro {tipo}* possui o seguinte cenário: {motivo}\n\n"
            f"Como sua segurança vem sempre em primeiro lugar, recomendamos tomar os seguintes cuidados imediatamente:\n"
        )

        if tipo == "Automóvel":
            mensagem += (
                "🔹 *1.* Busque estacionar seu veículo em garagens cobertas ou locais elevados e seguros.\n"
                "🔹 *2.* Evite estacionar abaixo de árvores, postes, redes elétricas ou painéis de publicidade.\n"
                "🔹 *3.* Evite trafegar por vias com histórico conhecido de alagamento ou baixa visibilidade."
            )
        elif tipo == "Residencial":
            mensagem += (
                "🔹 *1.* Mantenha ralos, calhas e condutores limpos para evitar o acúmulo de água no telhado.\n"
                "🔹 *2.* Retire eletrodomésticos sensíveis das tomadas para prevenir queimas devido a descargas elétricas.\n"
                "🔹 *3.* Mantenha portas e janelas fechadas e evite proximidade com vidraças durante vendavais."
            )
        elif tipo == "Empresarial":
            mensagem += (
                "🔹 *1.* Proteja mercadorias e estoques elevados acima do nível do solo para evitar danos de inundação.\n"
                "🔹 *2.* Garanta que os sistemas de drenagem do galpão/comércio estejam totalmente desobstruídos.\n"
                "🔹 *3.* Reforce coberturas soltas e mantenha equipes operacionais cientes dos procedimentos de segurança."
            )
        else:
            mensagem += (
                "🔹 *1.* Permaneça em local seguro e evite deslocamentos desnecessários durante a tempestade.\n"
                "🔹 *2.* Mantenha contatos de emergência e canais de comunicação com bateria carregada.\n"
                "🔹 *3.* Siga estritamente as orientações locais fornecidas pela Defesa Civil da sua cidade."
            )

        mensagem += (
            f"\n\nEstamos acompanhando as condições meteorológicas em tempo real. "
            f"Se precisar de socorro ou assistência 24h, estamos prontos no WhatsApp ou fone 0800-123-4567. "
            f"Conte conosco! 🤝"
        )
        return self._registrar_motor("template-local", mensagem)


# =====================================================================
# SIMULADOR DE ENVIO (NotificationSimulator)
# =====================================================================
class NotificationSimulator:
    """
    Simulador que demonstra a etapa final da solução (envio de notificações),
    imprimindo os canais e formatos de forma organizada para avaliação e testes.
    """
    def enviar(
        self, segurado: Dict[str, Any], mensagem: str, motor: str = "template-local"
    ) -> Dict[str, Any]:
        print("\n" + "="*80)
        print(f"📡 DISPARO DE NOTIFICAÇÃO PROATIVA - CANAL MULTICHANNEL")
        print("="*80)
        print(f"👤 Destinatário: {segurado['nome']}")
        print(f"📧 E-mail: {segurado['email']} | 📞 SMS/WhatsApp: {segurado['telefone']}")
        print(f"🏠 Cidade de Risco: {segurado['cidade']} - {segurado['uf']}")
        print(f"📄 Tipo de Seguro: {segurado['tipo_seguro']}")
        print(f"🚨 Severidade do Alerta: {segurado['contexto_alerta']['severidade']}")
        print(f"🤖 Mensagem redigida por: {motor}")
        print("-"*80)
        print(mensagem)
        print("="*80 + "\n")

        # O registro devolvido alimenta o consolidado da execução gravado por --salvar.
        return {
            "segurado": segurado["nome"],
            "email": segurado["email"],
            "telefone": segurado["telefone"],
            "cidade": f"{segurado['cidade']} - {segurado['uf']}",
            "tipo_seguro": segurado["tipo_seguro"],
            "eventos": segurado["contexto_alerta"]["eventos"],
            "severidade": segurado["contexto_alerta"]["severidade"],
            "regra_de_negocio": segurado["contexto_alerta"]["motivo_regrade_negocio"],
            "motor_de_geracao": motor,
            "mensagem": mensagem,
        }


# =====================================================================
# CENÁRIOS CONTROLADOS PARA DEMONSTRAÇÃO
# =====================================================================
def carregar_cenarios_demo() -> Dict[str, Any]:
    """
    Carrega os cenários climáticos controlados e a carteira fictícia usados no modo `--demo`.
    """
    try:
        with open(ARQUIVO_CENARIOS_DEMO, "r", encoding="utf-8") as f:
            demo = json.load(f)
        logger.info(
            f"[Database] Cenários de demonstração carregados de '{os.path.basename(ARQUIVO_CENARIOS_DEMO)}' "
            f"({len(demo.get('cenarios', {}))} cenários / {len(demo.get('segurados', []))} segurados)."
        )
        return demo
    except Exception as e:
        logger.error(f"[Database] Erro ao carregar os cenários de demonstração: {str(e)}")
        return {"cenarios": {}, "segurados": []}


# =====================================================================
# ORQUESTRAÇÃO DO FLUXO COMPLETO (Pipeline Principal)
# =====================================================================
def executar_pipeline_proativo(
    provider: str = "auto",
    modo_demo: bool = False,
    cidade_filtro: Optional[str] = None,
    salvar: bool = False,
) -> Dict[str, Any]:
    """
    Executa o fluxo ponta a ponta: coleta → análise → regras de negócio → geração → envio.
    """
    modo_texto = "DEMONSTRAÇÃO (cenários controlados)" if modo_demo else "TEMPO REAL (avisos ativos do INMET)"
    print("\n" + "#"*80)
    print("🚀 INICIANDO O SISTEMA DE COMUNICAÇÃO PROATIVA COM SEGURADOS - I2A2 (MVP)")
    print(f"   Modo de execução: {modo_texto}")
    print("#"*80)

    # 1. Base de segurados e Agente Coletor (tempo real ou demonstração)
    if modo_demo:
        demo = carregar_cenarios_demo()
        database_segurados = demo.get("segurados", [])
        coletor = DemoDataCollectorAgent(demo.get("cenarios", {}))
    else:
        database_segurados = carregar_base_segurados()
        coletor = DataCollectorAgent()

    # 2. Demais agentes do pipeline
    analisador = WeatherAnalyzerAgent()
    decisor = BusinessRulesAgent()
    gerador_mensagem = MessageGeneratorAgent(api_provider=provider)
    disparador = NotificationSimulator()

    # As cidades monitoradas são derivadas da própria carteira, de modo que nenhum
    # município presente na base fique fora da varredura.
    cidades_monitorar: List[Tuple[str, str]] = []
    vistas = set()
    for segurado in database_segurados:
        if cidade_filtro and segurado["cidade"].strip().lower() != cidade_filtro.strip().lower():
            continue
        chave = (segurado["cidade"], segurado.get("uf"))
        if chave not in vistas:
            vistas.add(chave)
            cidades_monitorar.append(chave)

    if not cidades_monitorar:
        logger.error(f"Nenhum segurado encontrado na carteira para a cidade '{cidade_filtro}'.")

    notificacoes: List[Dict[str, Any]] = []
    cidades_com_evento: List[str] = []

    # 3. Execução do fluxo coordenado ponta a ponta
    for cidade, uf in cidades_monitorar:
        print(f"\n⚡ [FLUXO] Iniciando varredura para a cidade: {cidade} - {uf}...")

        # Etapa 1: Coleta dos Dados Meteorológicos
        dados_clima = coletor.coletar_dados(cidade, uf)

        # Etapa 2: Análise de Riscos Climáticos
        analise_risco = analisador.analisar_risco(dados_clima)
        if analise_risco.get("requer_comunicacao"):
            cidades_com_evento.append(f"{cidade} - {uf}")

        # Etapa 3: Aplicação de Regras de Negócio sobre a carteira de segurados
        segurados_para_notificar = decisor.determinar_elegibilidade(analise_risco, database_segurados)

        if not segurados_para_notificar:
            print(f"🟢 [FLUXO] Concluído para {cidade}. Nenhuma comunicação preventiva necessária.")
            continue

        # Etapa 4 & 5: Geração Automatizada e Simulação de Envio
        for segurado in segurados_para_notificar:
            # Redação personalizada pelo LLM ou pelo gerador local
            mensagem_final = gerador_mensagem.gerar_comunicacao_preventiva(segurado)

            # Simulação do envio multicanal
            notificacoes.append(
                disparador.enviar(segurado, mensagem_final, gerador_mensagem.ultimo_motor)
            )

    resumo = {
        "executado_em": datetime.now().isoformat(timespec="seconds"),
        "modo": "demonstracao" if modo_demo else "tempo_real",
        "fonte_de_dados": os.path.basename(ARQUIVO_CENARIOS_DEMO) if modo_demo else DataCollectorAgent.URL_AVISOS_INMET,
        "motor_de_geracao": gerador_mensagem.api_provider,
        "modelo": gerador_mensagem.modelo_em_uso,
        "mensagens_por_motor": dict(gerador_mensagem.motores_utilizados),
        "cidades_monitoradas": len(cidades_monitorar),
        "cidades_com_evento_climatico": cidades_com_evento,
        "total_notificacoes": len(notificacoes),
        "notificacoes": notificacoes,
    }

    print("\n" + "#"*80)
    print("🏁 PIPELINE CONCLUÍDO COM SUCESSO!")
    print(f"Fonte de dados meteorológicos: {resumo['fonte_de_dados']}")
    print(f"Motor de geração das mensagens: {resumo['motor_de_geracao']} ({resumo['modelo']})")
    if resumo["mensagens_por_motor"]:
        detalhe = ", ".join(f"{motor}: {qtd}" for motor, qtd in resumo["mensagens_por_motor"].items())
        print(f"Mensagens efetivamente redigidas por: {detalhe}")
    print(f"Total de cidades monitoradas: {resumo['cidades_monitoradas']}")
    print(f"Cidades com evento climático relevante: {len(cidades_com_evento)} {cidades_com_evento if cidades_com_evento else ''}")
    print(f"Total de comunicações preventivas geradas e enviadas: {resumo['total_notificacoes']}")
    print("#"*80 + "\n")

    if salvar:
        _salvar_resumo(resumo)

    return resumo


def _salvar_resumo(resumo: Dict[str, Any]) -> str:
    """Grava as notificações geradas em `saida/`, servindo de evidência da execução."""
    os.makedirs(DIR_SAIDA, exist_ok=True)
    nome = f"notificacoes_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    caminho = os.path.join(DIR_SAIDA, nome)
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(resumo, f, ensure_ascii=False, indent=2)
    logger.info(f"[Saída] Execução registrada em '{os.path.join('saida', nome)}'.")
    return caminho


# =====================================================================
# INTERFACE DE LINHA DE COMANDO
# =====================================================================
def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Comunicação proativa com segurados a partir de eventos climáticos (Desafio 5 - I2A2).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Exemplos:\n"
            "  python main.py                       Executa com os avisos reais do INMET\n"
            "  python main.py --demo                Executa os cenários controlados de demonstração\n"
            "  python main.py --provider gemini     Redige as mensagens com o Google Gemini\n"
            "  python main.py --cidade Curitiba     Analisa apenas uma cidade da carteira\n"
            "  python main.py --demo --salvar       Salva as notificações em saida/*.json\n"
        ),
    )
    parser.add_argument(
        "--provider",
        choices=["auto", "openai", "gemini", "simulation"],
        default="auto",
        help="Motor de redação das mensagens. 'auto' (padrão) usa o LLM se houver chave no .env.",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Usa cenários climáticos controlados em vez da API do INMET (demonstração completa).",
    )
    parser.add_argument(
        "--cidade",
        default=None,
        help="Restringe a varredura a uma única cidade da carteira.",
    )
    parser.add_argument(
        "--salvar",
        action="store_true",
        help="Grava as notificações geradas em saida/notificacoes_<data>.json.",
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = _parse_args()
    executar_pipeline_proativo(
        provider=args.provider,
        modo_demo=args.demo,
        cidade_filtro=args.cidade,
        salvar=args.salvar,
    )
