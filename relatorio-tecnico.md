# Relatório Técnico: Solução de Comunicação Proativa com o Segurado
**Desafio 5 — Instituto de Inteligência Artificial Aplicada (I2A2)**

**Grupo:** [InsurAi / Juan David Valle Sánchez, Rodrigo Silva Figueiredo, Isabela Del Rio, Karin Abe]
**Data:** [13-09-2026]

---

## 1. Introdução e Objetivo do Projeto

O modelo tradicional de relacionamento entre seguradoras e segurados é majoritariamente **reativo**: a comunicação só acontece depois que o sinistro já ocorreu. Este projeto propõe inverter essa lógica, monitorando condições climáticas de risco em tempo real e alertando o segurado **antes** que o dano aconteça, com orientações práticas de prevenção.

* **Problema Resolvido:** Falta de comunicação preventiva entre seguradora e cliente diante de eventos climáticos que colocam em risco bens segurados (imóveis, veículos e estabelecimentos comerciais).
* **Escopo da Solução:** Um pipeline automatizado de 4 agentes que (1) coleta avisos meteorológicos oficiais, (2) analisa e classifica o risco, (3) cruza o risco com a carteira de segurados e o tipo de apólice, e (4) gera e "envia" (simula o envio de) uma notificação preventiva personalizada.
* **Fonte de dados climáticos:** API pública de avisos ativos do **INMET** (Instituto Nacional de Meteorologia) — a mesma fonte oficial usada pela Defesa Civil e pela imprensa —, consultada em tempo real e sem necessidade de chave de API.

---

## 2. Arquitetura da Solução

O sistema é implementado como um pipeline sequencial de agentes, todos definidos em `main.py`, sem dependência de frameworks externos de orquestração.

```text
[ segurados.json ]                  [ API pública de avisos ativos do INMET ]
        │                                          │
        │ (Carteira de Segurados)                  │ (Avisos oficiais por município/UF)
        ▼                                          ▼
┌────────────────────────────┐        ┌─────────────────────────────────┐
│ carregar_base_segurados()  │        │      DataCollectorAgent          │
└──────────────┬─────────────┘        └──────────────────┬──────────────┘
               │                                          │ (chuva mm/h, vento km/h,
               │ (cidades/UF únicas monitoradas)           │  granizo, severidade oficial)
               │                                          ▼
               │                          ┌─────────────────────────────────┐
               │                          │      WeatherAnalyzerAgent        │
               │                          └──────────────────┬──────────────┘
               │                                              │ (eventos + nível de severidade)
               ▼                                              ▼
                          ┌─────────────────────────────────────────┐
                          │           BusinessRulesAgent             │
                          └──────────────────────┬────────────────────┘
                                                  │ (segurados elegíveis + contexto do alerta)
                                                  ▼
                          ┌─────────────────────────────────────────┐
                          │         MessageGeneratorAgent            │ <── OpenAI / Gemini / Template local
                          └──────────────────────┬────────────────────┘
                                                  │ (mensagem final personalizada)
                                                  ▼
                          ┌─────────────────────────────────────────┐
                          │        NotificationSimulator             │  (console)
                          └─────────────────────────────────────────┘
```

---

## 3. Descrição dos Agentes Desenvolvidos

### 3.1. `DataCollectorAgent` (Coletor)
* **Responsabilidade:** Consultar, para cada cidade/UF da carteira, a API pública `https://apiprevmet3.inmet.gov.br/avisos/ativos` e retornar o aviso de maior severidade vigente no dia.
* **Como funciona:** o método `_consultar_avisos_inmet` localiza o município dentro do campo `"municipios"` retornado pela API (busca por `"Cidade - UF"`). Como a API descreve os riscos em texto livre (ex.: *"Chuva entre 20 e 30 mm/h... ventos intensos (40-60 km/h)"*), o método `_extrair_metricas_dos_riscos` usa expressões regulares para extrair estimativas conservadoras (piores valores) de chuva (mm/h) e vento (km/h), além de detectar menção a granizo.
* Quando não há aviso ativo para a cidade, o clima é considerado estável (0 mm de chuva, vento baixo).

### 3.2. `WeatherAnalyzerAgent` (Analisador)
* **Responsabilidade:** Transformar as métricas brutas em eventos de risco qualitativos e um nível de severidade (`BAIXO`, `ALTO`, `CRITICO`).
* **Regras implementadas:**
  1. Chuva ≥ 30 mm/h → `Alagamento / Enxurrada` (CRÍTICO); chuva ≥ 15 mm/h → `Chuva Forte` (ALTO).
  2. Vento ≥ 60 km/h → `Ciclone / Vendaval Forte` (CRÍTICO); vento ≥ 40 km/h → `Ventos Fortes` (ALTO).
  3. Menção a granizo no aviso → `Queda de Granizo` (ALTO).
  4. Chuva ≥ 40 mm/h no Rio de Janeiro → `Risco Altíssimo de Deslizamento` (CRÍTICO), por concentrar segurados em áreas de encosta.

### 3.3. `BusinessRulesAgent` (Decisor)
* **Responsabilidade:** Cruzar os eventos identificados com o tipo de apólice (`Residencial`, `Empresarial`, `Automóvel`) e os `detalhes_seguro` de cada segurado, filtrando apenas quem reside na cidade afetada e cuja cobertura faz sentido para o risco.
* **Exemplos de regras de cruzamento:**
  * `Alagamento / Enxurrada` → Residencial/Empresarial sempre elegíveis; Automóvel elegível se o segurado não possui garagem coberta.
  * `Queda de Granizo` → Automóvel (avarias na lataria/vidros) e Residencial (telhados/vidraças).
  * `Ciclone / Vendaval Forte` ou `Ventos Fortes` → Residencial/Empresarial (danos estruturais) e Automóvel (queda de galhos/árvores).
  * `Risco Altíssimo de Deslizamento` → Residencial cujo `detalhes_seguro` menciona "encosta".

### 3.4. `MessageGeneratorAgent` (Redator)
* **Responsabilidade:** Redigir a notificação final, com 3 opções de motor, selecionadas via `api_provider`:
  * `openai` (`gpt-4o-mini`, via `OPENAI_API_KEY`);
  * `gemini` (`gemini-1.5-flash`, via `GEMINI_API_KEY`);
  * `simulation` (padrão): gerador local baseado em templates por tipo de seguro, usado como fallback automático caso nenhuma chave esteja configurada ou a chamada à API externa falhe.
* **System Prompt utilizado:**
  > *"Você é a inteligência proativa de uma Seguradora de alta confiabilidade. Seu tom deve ser empático, urgente mas não alarmista, e focado em segurança física e material. Gere uma mensagem curta, estruturada em tópicos curtos de prevenção, direta e personalizada, evitando termos burocráticos ou robóticos."*

### 3.5. `NotificationSimulator` e `carregar_base_segurados`
* `carregar_base_segurados()` carrega a carteira de `segurados.json`, recriando o arquivo com um registro mínimo caso não exista.
* `NotificationSimulator` imprime no console o "disparo" da notificação (destinatário, e-mail, telefone, cidade/UF, tipo de seguro, severidade e o corpo da mensagem), simulando o canal multicanal (e-mail/SMS/WhatsApp) sem integração real de envio.

---

## 4. Tecnologias Utilizadas

* **Linguagem:** Python 3.12+.
* **Orquestração de Agentes:** implementação própria, sem framework externo (4 classes de agentes + 2 funções utilitárias em `main.py`).
* **API Meteorológica:** API pública de avisos ativos do INMET (`https://apiprevmet3.inmet.gov.br/avisos/ativos`), sem necessidade de chave.
* **API de IA Generativa (opcional):** OpenAI (`gpt-4o-mini`) ou Google Gemini (`gemini-1.5-flash`); ambas com fallback automático para o gerador local de templates.
* **Bibliotecas Python:**
  * `requests` — consumo da API do INMET;
  * `openai` e `google-generativeai` — integração opcional com LLMs;
  * `python-dotenv` — carregamento de `OPENAI_API_KEY` / `GEMINI_API_KEY` a partir do `.env`.
* **Persistência da carteira de segurados:** arquivo `segurados.json` (27 registros, um por unidade federativa do Brasil).
* **Interface de Demonstração:** CLI (saída formatada diretamente no console via `print`).

---

## 5. Fluxo de Processamento Ponta a Ponta

1. `carregar_base_segurados()` lê `segurados.json` e retorna a lista de segurados.
2. O pipeline deriva dinamicamente a lista de cidades/UF a monitorar a partir dos pares únicos `(cidade, uf)` presentes na carteira — nenhuma cidade da base fica de fora da análise.
3. Para cada cidade: `DataCollectorAgent.coletar_dados(cidade, uf)` consulta a API do INMET e retorna as métricas climáticas (ou "clima estável" se não houver aviso ativo).
4. `WeatherAnalyzerAgent.analisar_risco(...)` classifica os eventos de risco e a severidade.
5. `BusinessRulesAgent.determinar_elegibilidade(...)` filtra, dentro da carteira, os segurados elegíveis para receber o alerta.
6. Para cada segurado elegível, `MessageGeneratorAgent.gerar_comunicacao_preventiva(...)` redige a mensagem personalizada.
7. `NotificationSimulator.enviar(...)` imprime o "disparo" da notificação no console.
8. Ao final, o pipeline exibe o total de cidades monitoradas e o total de notificações enviadas.

---

## 6. Exemplos de Mensagens Geradas

Os exemplos abaixo foram capturados em uma execução real do sistema (`python main.py`), com avisos oficiais do INMET ativos no momento da consulta.

### Cenário A: Alagamento, Vendaval e Granizo em Vitória/ES (Seguro Empresarial)
* **Segurado:** Juliana Martins — Escritório de advocacia na Enseada do Suá.
* **Aviso oficial INMET:** Tempestade — Perigo Potencial.
* **Eventos detectados:** `Alagamento / Enxurrada`, `Ciclone / Vendaval Forte`, `Queda de Granizo` (severidade ALTO).
* **Motivo de elegibilidade:** Risco de destelhamento e danos estruturais no imóvel.

### Cenário B: Alagamento, Vendaval e Granizo em Belo Horizonte/MG (Seguro Residencial)
* **Segurado:** Rodrigo Mendes — Apartamento na Savassi.
* **Aviso oficial INMET:** Tempestade — Perigo Potencial.
* **Eventos detectados:** `Alagamento / Enxurrada`, `Ciclone / Vendaval Forte`, `Queda de Granizo` (severidade ALTO).
* **Motivo de elegibilidade:** Risco de destelhamento e danos estruturais no imóvel.

### Cenário C: Risco no Rio de Janeiro/RJ (Seguro Automóvel)
* **Segurado:** Vanessa Ramos — Crossover urbano, Placa RIO-2345.
* **Aviso oficial INMET:** Tempestade — Perigo Potencial.
* **Motivo de elegibilidade:** Alto risco de queda de galhos/árvores sobre o veículo estacionado.

### Cenário D: Tempestade severa em Porto Alegre/RS (Seguro Empresarial)
* **Segurado:** Gustavo Farias — Indústria metalúrgica em Caxias do Sul.
* **Aviso oficial INMET:** Tempestade — Perigo (severidade mais alta que "Perigo Potencial").
* **Motivo de elegibilidade:** Risco de destelhamento e danos estruturais no imóvel.

Em uma execução típica, das 27 cidades/UF monitoradas (uma por segurado cadastrado), tipicamente 3 a 5 possuem avisos oficiais ativos no INMET, gerando o mesmo número de notificações preventivas.

---

## 7. Conclusão e Próximos Passos

O MVP demonstra viabilidade técnica de um fluxo ponta a ponta totalmente automatizado — da consulta a uma fonte meteorológica oficial em tempo real até a redação de uma mensagem preventiva personalizada — sem exigir nenhuma chave de API paga para o núcleo do sistema (o INMET é público e gratuito). A geração de mensagens com LLM é plugável e opcional, com fallback local garantindo que o sistema nunca fique sem resposta.

**Melhorias sugeridas para um ambiente produtivo:**
* Substituir o `NotificationSimulator` por integrações reais de envio (e-mail transacional, SMS, WhatsApp Business API).
* Persistir o histórico de alertas e notificações em um banco de dados, evitando reenvios duplicados para o mesmo evento.
* Ampliar a Regra 4 (deslizamento) para qualquer cidade cujos segurados residam em áreas de encosta, hoje restrita ao Rio de Janeiro.
* Adicionar testes automatizados para as regras de negócio do `BusinessRulesAgent` e do `WeatherAnalyzerAgent`.
* Avaliar uso de cache/agendamento (ex.: execução periódica via cron) em vez de consulta síncrona a cada execução manual.

