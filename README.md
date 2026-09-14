# Ferramenta Inteligente para Comunicação Proativa com o Segurado (Desafio 5)

Protótipo funcional (MVP) de uma solução multiagente de **comunicação preventiva** para seguradoras.
O sistema consulta em tempo real a API pública de avisos ativos do **INMET** (Instituto Nacional de
Meteorologia), identifica automaticamente os eventos climáticos de risco vigentes, cruza esses eventos
com a carteira de segurados e utiliza **IA Generativa (LLM)** — com um gerador local de templates como
fallback — para redigir notificações personalizadas **antes que o sinistro ocorra**.

> **Grupo:** InsurAi — Juan David Valle Sánchez, Rodrigo Silva Figueiredo, Isabela Del Rio, Karin Abe
> **Curso:** InsurMinds — Instituto de Inteligência Artificial Aplicada (I2A2)

---

## 🧭 Visão Geral do Fluxo

```text
┌──────────────────────┐   ┌──────────────────────┐   ┌──────────────────────┐   ┌──────────────────────┐   ┌──────────────────────┐
│  1. DataCollector    │──▶│  2. WeatherAnalyzer  │──▶│  3. BusinessRules    │──▶│  4. MessageGenerator │──▶│  5. Notification     │
│      Agent           │   │      Agent           │   │      Agent           │   │      Agent (LLM)     │   │      Simulator       │
│  Coleta (INMET)      │   │  Identifica eventos  │   │  Aplica regras de    │   │  Redige a mensagem   │   │  Simula o envio      │
│                      │   │  e severidade        │   │  apólice/geografia   │   │  personalizada       │   │  multicanal          │
└──────────────────────┘   └──────────────────────┘   └──────────────────────┘   └──────────────────────┘   └──────────────────────┘
          ▲                                                      ▲
   API pública do INMET                                   segurados.json
```

Cada etapa exigida pelo desafio corresponde a um agente especializado, com responsabilidade única.

---

## 🚀 Como Executar o Projeto

### Pré-requisitos
* **Python 3.12+** e o gerenciador de pacotes **pip**
* Conexão com a internet (para consultar a API pública do INMET e, opcionalmente, o LLM)
* (Opcional) Uma chave de API de LLM — Google Gemini ou OpenAI

### 1. Clonar o Repositório
```bash
git clone https://github.com/abe-karin/alerta-insurAI-.git
cd alerta-insurAI-
```

### 2. Configurar o Ambiente Virtual
```bash
python -m venv venv

# Windows:
venv\Scripts\activate
# Linux/macOS:
source venv/bin/activate
```

### 3. Instalar Dependências
```bash
pip install -r requirements.txt
```

### 4. Configurar as Variáveis de Ambiente (opcional)
A API de avisos do INMET é pública e **não exige chave**. As variáveis abaixo só são necessárias
para que o `MessageGeneratorAgent` redija as mensagens com um LLM real. Copie o modelo e preencha:

```bash
# Windows:
copy .env.example .env
# Linux/macOS:
cp .env.example .env
```

```bash
# Conteúdo do .env
GEMINI_API_KEY=sua_chave_do_google_gemini
OPENAI_API_KEY=sua_chave_da_openai
```

> **⚠️ Importante:** o arquivo `.env` já está listado no `.gitignore` e **nunca** deve ser versionado.
> Sem nenhuma chave configurada o sistema continua funcionando: o agente redator cai automaticamente
> no gerador local de templates.

### 5. Executar a Aplicação
```bash
python main.py
```
O pipeline varre todas as cidades presentes em `segurados.json`, consulta os avisos oficiais do INMET
e imprime no console cada notificação preventiva gerada.

---

## 🎛️ Modos de Execução (CLI)

| Comando | O que faz |
| --- | --- |
| `python main.py` | Execução padrão: dados reais do INMET; usa LLM se houver chave no `.env`, senão o gerador local. |
| `python main.py --demo` | **Demonstração garantida:** usa 5 cenários climáticos controlados (`cenarios_demo.json`) em vez da API, exercitando todos os tipos de evento e de apólice mesmo em um dia sem avisos ativos no país. |
| `python main.py --provider gemini` | Força a redação das mensagens com o Google Gemini (`auto`, `openai`, `gemini` ou `simulation`). |
| `python main.py --cidade Curitiba` | Restringe a varredura a uma única cidade da carteira. |
| `python main.py --salvar` | Grava as notificações geradas em `saida/notificacoes_<data>.json` (evidência da execução). |

Exemplo de demonstração completa, ponta a ponta, com registro em disco:
```bash
python main.py --demo --salvar
```

---

## 🧪 Testes Automatizados

A suíte cobre as cinco etapas do pipeline e roda **sem acesso à rede e sem chave de API**:

```bash
python -m unittest discover -s tests -v
```

São 29 testes que validam a leitura do texto oficial dos avisos do INMET, os limiares de severidade,
o cruzamento evento × apólice, a personalização das mensagens, o simulador de envio e uma execução
ponta a ponta em modo de demonstração.

---

## 🛠️ Tecnologias Utilizadas

* **Linguagem:** Python 3.12+
* **Orquestração de Agentes:** implementação própria (5 classes de agentes em `main.py`), sem framework externo
* **API Meteorológica:** API pública de avisos ativos do INMET — `https://apiprevmet3.inmet.gov.br/avisos/ativos`
* **Modelos de Linguagem (LLM):** Google Gemini (`gemini-2.0-flash`) ou OpenAI (`gpt-4o-mini`), com fallback automático para o gerador local de templates
* **Bibliotecas:** `requests`, `python-dotenv`, `openai`, `google-generativeai`
* **Testes:** `unittest` (biblioteca padrão)
* **Interface de Demonstração:** CLI (`argparse`), com saída formatada no terminal

---

## 📦 Estrutura do Código-Fonte

```text
├── main.py                # Pipeline completo: os 5 agentes + orquestração + CLI
├── segurados.json         # Carteira de segurados (27 registros, um por UF)
├── cenarios_demo.json     # Cenários climáticos controlados usados no modo --demo
├── tests/
│   └── test_pipeline.py   # Suíte de testes automatizados (29 testes)
├── requirements.txt       # Dependências do projeto
├── .env.example           # Modelo das variáveis de ambiente (chaves de LLM)
├── relatorio-tecnico.md   # Relatório técnico do desafio
├── LICENSE                # Licença MIT
└── README.md              # Este arquivo
```

Dentro de `main.py`, o pipeline é composto por:

| Componente | Responsabilidade |
| --- | --- |
| `carregar_base_segurados()` | Carrega/inicializa a carteira em `segurados.json`. |
| `DataCollectorAgent` | Consulta os avisos ativos do INMET (uma única requisição por execução, mantida em cache) e extrai chuva (mm/h), vento (km/h) e menção a granizo do texto oficial. |
| `DemoDataCollectorAgent` | Variante que injeta cenários controlados no lugar da API, para demonstração. |
| `WeatherAnalyzerAgent` | Classifica os eventos (Alagamento, Chuva Forte, Vendaval, Granizo, Deslizamento) e o nível de severidade. |
| `BusinessRulesAgent` | Cruza os eventos com a geografia e o tipo de apólice de cada segurado, acumulando todos os motivos de elegibilidade. |
| `MessageGeneratorAgent` | Redige a notificação via Gemini, OpenAI ou gerador local (fallback automático em qualquer falha). |
| `NotificationSimulator` | Imprime o disparo multicanal (e-mail/SMS/WhatsApp) e devolve o registro da notificação. |

---

## 📐 Regras de Negócio Implementadas

**Identificação do evento climático** (`WeatherAnalyzerAgent`):

| Condição | Evento | Severidade |
| --- | --- | --- |
| Chuva ≥ 30 mm/h | Alagamento / Enxurrada | CRÍTICO |
| Chuva ≥ 15 mm/h | Chuva Forte | ALTO |
| Vento ≥ 60 km/h | Ciclone / Vendaval Forte | CRÍTICO |
| Vento ≥ 40 km/h | Ventos Fortes | ALTO |
| Menção a granizo no aviso | Queda de Granizo | ALTO |
| Chuva ≥ 40 mm/h em município com ocupação em encostas | Risco Altíssimo de Deslizamento | CRÍTICO |

**Elegibilidade do segurado** (`BusinessRulesAgent`) — além de residir na cidade afetada:

| Evento | Quem é notificado |
| --- | --- |
| Alagamento / Enxurrada | Residencial e Empresarial; Automóvel apenas se não possui garagem coberta |
| Queda de Granizo | Automóvel (lataria/vidros) e Residencial (telhados/vidraças) |
| Ventos Fortes / Vendaval | Residencial e Empresarial (destelhamento); Automóvel (queda de árvores) |
| Deslizamento | Residencial e Empresarial cujo cadastro indique imóvel em encosta/morro/ladeira |

---

## 📜 Licença

Este projeto está licenciado sob a **Licença MIT** — consulte o arquivo [LICENSE](LICENSE) para o texto completo.
