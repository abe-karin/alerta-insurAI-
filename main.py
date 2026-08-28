import os
import json
import logging
import re
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv

load_dotenv()  # carrega variáveis do arquivo .env para o ambiente

# Configuração do Logging para visualização clara no terminal
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [%(levelname)s] - %(name)s: %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("I2A2-Desafio5")

# Nome padrão do arquivo externo de banco de dados de segurados
ARQUIVO_SEGURADOS = "segurados.json"

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

    def __init__(self):
        self.name = "Agente_Coletor"
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
        import requests
        termo_busca = f"{cidade} - {uf}"
        try:
            response = requests.get(self.URL_AVISOS_INMET, timeout=10)
            if response.status_code != 200:
                logger.error(f"[{self.name}] Erro na chamada à API do INMET ({response.status_code}).")
                return None
            avisos_hoje = response.json().get("hoje", [])
            avisos_relevantes = [
                aviso for aviso in avisos_hoje
                if termo_busca in aviso.get("municipios", "")
            ]
            if not avisos_relevantes:
                return None
            pior_aviso = max(avisos_relevantes, key=lambda a: a.get("id_severidade", 0))
            logger.info(f"[{self.name}] Aviso oficial do INMET encontrado para {cidade}: {pior_aviso.get('severidade')} - {pior_aviso.get('descricao')}")
            return {
                "severidade": pior_aviso.get("severidade"),
                "descricao": pior_aviso.get("descricao"),
                "riscos": pior_aviso.get("riscos", []),
            }
        except Exception as e:
            logger.error(f"[{self.name}] Falha ao consultar a API do INMET: {str(e)}")
            return None

    def _extrair_metricas_dos_riscos(self, riscos: List[str]) -> tuple:
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

        # Regra 4: Deslizamento de Terra (Condições de chuva volumosa em áreas de encosta)
        if chuva >= 40.0 and dados_clima["cidade"] == "Rio de Janeiro":
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

            elegivel = False
            motivo_elegibilidade = ""

            # Regras Cruzadas de Apólice e Evento:
            # 1. Alagamento -> Afeta principalmente Seguro Residencial ou Empresarial de rua
            if "Alagamento / Enxurrada" in eventos:
                if segurado["tipo_seguro"] in ["Residencial", "Empresarial"]:
                    elegivel = True
                    motivo_elegibilidade = "Risco de inundação do imóvel segurado devido a volume de chuva crítico."
                elif segurado["tipo_seguro"] == "Automóvel" and "Não possui garagem coberta" in segurado["detalhes_seguro"]:
                    # Se for seguro Auto e não tiver garagem coberta, também avisamos
                    elegivel = True
                    motivo_elegibilidade = "Risco de alagamento do veículo que estaciona em via pública."

            # 2. Queda de Granizo -> Afeta gravemente apólices de Automóvel e Residencial (telhados)
            if "Queda de Granizo" in eventos:
                if segurado["tipo_seguro"] == "Automóvel":
                    elegivel = True
                    motivo_elegibilidade = "Risco de avarias na lataria e vidros do veículo segurado."
                elif segurado["tipo_seguro"] == "Residencial":
                    elegivel = True
                    motivo_elegibilidade = "Risco de quebra de telhados e vidraças do imóvel."

            # 3. Ventos Fortes ou Ciclone -> Afeta Residencial, Empresarial e Automóvel (queda de árvores)
            if "Ciclone / Vendaval Forte" in eventos or "Ventos Fortes" in eventos:
                if segurado["tipo_seguro"] in ["Residencial", "Empresarial"]:
                    elegivel = True
                    motivo_elegibilidade = "Risco de destelhamento e danos estruturais no imóvel."
                elif segurado["tipo_seguro"] == "Automóvel":
                    elegivel = True
                    motivo_elegibilidade = "Alto risco de queda de galhos/árvores sobre o veículo estacionado."

            # 4. Deslizamento -> Altamente crítico para residências em encostas
            if "Risco Altíssimo de Deslizamento" in eventos:
                if segurado["tipo_seguro"] == "Residencial" and "encosta" in segurado["detalhes_seguro"].lower():
                    elegivel = True
                    motivo_elegibilidade = "Alerta máximo de evacuação preventiva e proteção de vidas."

            if elegivel:
                # Criamos um payload unificado com as informações do segurado, os dados do evento e o contexto
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
    def __init__(self, api_provider: str = "simulation"):
        self.name = "Agente_Redator_IA"
        self.api_provider = api_provider  # "openai", "gemini" ou "simulation"
        
        # Carrega chaves de API das variáveis de ambiente caso disponíveis
        self.openai_key = os.getenv("OPENAI_API_KEY")
        self.gemini_key = os.getenv("GEMINI_API_KEY")

        if self.api_provider == "openai" and self.openai_key:
            logger.info(f"[{self.name}] Utilizando OpenAI (GPT-4o/GPT-3.5) para geração de mensagens.")
        elif self.api_provider == "gemini" and self.gemini_key:
            logger.info(f"[{self.name}] Utilizando Google Gemini para geração de mensagens.")
        else:
            self.api_provider = "simulation"
            logger.info(f"[{self.name}] Utilizando motor cognitivo interno de simulação (Local Template Generator).")

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

        # Definição da Persona e Diretrizes de Escrita (Engenharia de Prompt)
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

        if self.api_provider == "openai":
            return self._chamar_openai(system_prompt, user_content)
        elif self.api_provider == "gemini":
            return self._chamar_gemini(system_prompt, user_content)
        else:
            return self._gerar_simulacao_heuristica(dados_elegibilidade)

    def _chamar_openai(self, system_prompt: str, user_prompt: str) -> str:
        """Chamada real utilizando a biblioteca oficial 'openai'."""
        try:
            from openai import OpenAI
            client = OpenAI(api_key=self.openai_key)
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.7,
                max_tokens=300
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.error(f"[{self.name}] Falha ao conectar à API da OpenAI: {str(e)}. Revertendo para gerador local.")
            return self._gerar_simulacao_heuristica(None)

    def _chamar_gemini(self, system_prompt: str, user_prompt: str) -> str:
        """Chamada real utilizando a biblioteca oficial 'google-generativeai'."""
        try:
            import google.generativeai as genai
            genai.configure(api_key=self.gemini_key)
            model = genai.GenerativeModel('gemini-1.5-flash')
            prompt_completo = f"{system_prompt}\n\nInstrução:\n{user_prompt}"
            response = model.generate_content(prompt_completo)
            return response.text.strip()
        except Exception as e:
            logger.error(f"[{self.name}] Falha ao conectar à API do Gemini: {str(e)}. Revertendo para gerador local.")
            return self._gerar_simulacao_heuristica(None)

    def _gerar_simulacao_heuristica(self, dados: Dict[str, Any]) -> str:
        """
        Gerador de mensagens local, rico e de alta fidelidade que simula perfeitamente
        o comportamento e o tom de uma IA generativa especializada em prevenção.
        """
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
        return mensagem


# =====================================================================
# SIMULADOR DE ENVIO (NotificationSimulator)
# =====================================================================
class NotificationSimulator:
    """
    Simulador que demonstra a etapa final da solução (envio de notificações),
    imprimindo os canais e formatos de forma organizada para avaliação e testes.
    """
    def enviar(self, segurado: Dict[str, Any], mensagem: str):
        print("\n" + "="*80)
        print(f"📡 DISPARO DE NOTIFICAÇÃO PROATIVA - CANAL MULTICHANNEL")
        print("="*80)
        print(f"👤 Destinatário: {segurado['nome']}")
        print(f"📧 E-mail: {segurado['email']} | 📞 SMS/WhatsApp: {segurado['telefone']}")
        print(f"🏠 Cidade de Risco: {segurado['cidade']} - {segurado['uf']}")
        print(f"📄 Tipo de Seguro: {segurado['tipo_seguro']}")
        print(f"🚨 Severidade do Alerta: {segurado['contexto_alerta']['severidade']}")
        print("-"*80)
        print(mensagem)
        print("="*80 + "\n")


# =====================================================================
# ORQUESTRAÇÃO DO FLUXO COMPLETO (Pipeline Principal)
# =====================================================================
def executar_pipeline_proativo():
    print("\n" + "#"*80)
    print("🚀 INICIANDO O SISTEMA DE COMUNICAÇÃO PROATIVA COM SEGURADOS - I2A2 (MVP)")
    print("#"*80)

    # 1. Carregando a Base de Dados de Segurados a partir do arquivo JSON separado
    database_segurados = carregar_base_segurados()

    # 2. Instanciando os Agentes
    coletor = DataCollectorAgent()
    analisador = WeatherAnalyzerAgent()
    decisor = BusinessRulesAgent()
    gerador_mensagem = MessageGeneratorAgent(api_provider="simulation")
    disparador = NotificationSimulator()

    # Cidades monitoradas: derivadas dinamicamente da carteira de segurados carregada,
    # garantindo que nenhuma cidade presente em segurados.json fique de fora da análise.
    cidades_monitorar = []
    vistas = set()
    for segurado in database_segurados:
        chave = (segurado["cidade"], segurado.get("uf"))
        if chave not in vistas:
            vistas.add(chave)
            cidades_monitorar.append(chave)

    total_notificacoes_enviadas = 0

    # 3. Execução do fluxo coordenado ponta a ponta
    for cidade, uf in cidades_monitorar:
        print(f"\n⚡ [FLUXO] Iniciando varredura para a cidade: {cidade} - {uf}...")
        
        # Etapa 1: Coleta dos Dados Meteorológicos
        dados_clima = coletor.coletar_dados(cidade, uf)
        
        # Etapa 2: Análise de Riscos Climáticos
        analise_risco = analisador.analisar_risco(dados_clima)
        
        # Etapa 3: Aplicação de Regras de Negócio utilizando a base de segurados externa
        segurados_para_notificar = decisor.determinar_elegibilidade(analise_risco, database_segurados)
        
        if not segurados_para_notificar:
            print(f"🟢 [FLUXO] Concluído para {cidade}. Nenhuma comunicação preventiva necessária.")
            continue

        # Etapa 4 & 5: Geração Automatizada e Simulação de Envio
        for segurado in segurados_para_notificar:
            # Geração de Mensagem personalizada (com IA real ou simulação)
            mensagem_final = gerador_mensagem.gerar_comunicacao_preventiva(segurado)
            
            # Simulação do Envio real
            disparador.enviar(segurado, mensagem_final)
            total_notificacoes_enviadas += 1

    print("\n" + "#"*80)
    print(f"🏁 PIPELINE CONCLUÍDO COM SUCESSO!")
    print(f"Total de cidades monitoradas: {len(cidades_monitorar)}")
    print(f"Total de comunicações preventivas geradas e enviadas: {total_notificacoes_enviadas}")
    print("#"*80 + "\n")


if __name__ == "__main__":
    executar_pipeline_proativo()
