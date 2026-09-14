# Relatório Técnico: Solução de Comunicação Proativa com o Segurado
**Desafio 5 — Instituto de Inteligência Artificial Aplicada (I2A2)**

**Grupo:** InsurAi — Juan David Valle Sánchez, Rodrigo Silva Figueiredo, Isabela Del Rio, Karin Abe
**Data:** 13/09/2026
**Repositório público:** https://github.com/abe-karin/alerta-insurAI-
**Licença:** MIT

---

## 1. Introdução e Objetivo do Projeto

O modelo tradicional de relacionamento entre seguradoras e segurados é majoritariamente **reativo**: a comunicação só acontece depois que o sinistro já ocorreu. Este projeto propõe inverter essa lógica, monitorando condições climáticas de risco em tempo real e alertando o segurado **antes** que o dano aconteça, com orientações práticas de prevenção.

* **Problema Resolvido:** Falta de comunicação preventiva entre seguradora e cliente diante de eventos climáticos que colocam em risco bens segurados (imóveis, veículos e estabelecimentos comerciais).
* **Escopo da Solução:** Um pipeline automatizado de agentes especializados que (1) coleta avisos meteorológicos oficiais, (2) analisa e classifica o risco, (3) cruza o risco com a carteira de segurados e o tipo de apólice, (4) gera a notificação preventiva personalizada com IA Generativa e (5) simula o envio multicanal.
* **Fonte de dados climáticos:** API pública de avisos ativos do **INMET** (Instituto Nacional de Meteorologia) — a mesma fonte oficial usada pela Defesa Civil e pela imprensa —, consultada em tempo real e sem necessidade de chave de API.

---

## 2. Arquitetura da Solução

O sistema é implementado como um pipeline sequencial de agentes especializados, todos definidos em `main.py`, sem dependência de frameworks externos de orquestração. Cada agente tem uma responsabilidade única e se comunica com o seguinte por meio de dicionários Python bem definidos.

```text
[ segurados.json ]                  [ API pública de avisos ativos do INMET ]
        │                                          │
        │ (Carteira de Segurados)                  │ (Avisos oficiais por município/UF)
        ▼                                          ▼
┌────────────────────────────┐        ┌─────────────────────────────────┐
│ carregar_base_segurados()  │        │      DataCollectorAgent          │
└──────────────┬─────────────┘        └──────────────────┬──────────────┘
               │                                          │ (chuva mm/h, vento km/h,
               │ (cidades/UF únicas monitoradas)          │  granizo, severidade oficial)
               │                                          ▼
               │                          ┌─────────────────────────────────┐
               │                          │      WeatherAnalyzerAgent        │
               │                          └──────────────────┬──────────────┘
               │                                             │ (eventos + nível de severidade)
               ▼                                             ▼
                          ┌─────────────────────────────────────────┐
                          │           BusinessRulesAgent             │
                          └──────────────────────┬──────────────────┘
                                                 │ (segurados elegíveis + contexto do alerta)
                                                 ▼
                          ┌─────────────────────────────────────────┐
                          │         MessageGeneratorAgent            │ ◀── Gemini / OpenAI / Template local
                          └──────────────────────┬──────────────────┘
                                                 │ (mensagem final personalizada)
                                                 ▼
                          ┌─────────────────────────────────────────┐
                          │        NotificationSimulator             │  (console + saida/*.json)
                          └─────────────────────────────────────────┘
```

### 2.1. Decisões de arquitetura

| Decisão | Justificativa |
| --- | --- |
| Agentes como classes independentes, orquestrados por uma função de pipeline | Mantém a separação exigida entre coleta, processamento, decisão e comunicação, e permite testar cada etapa isoladamente. |
| Carteira de segurados em arquivo externo (`segurados.json`) | Desacopla os dados de negócio do código; a lista de cidades monitoradas é derivada dinamicamente da carteira. |
| Uma única requisição à API do INMET por execução, mantida em cache | A API devolve todos os avisos vigentes do país em uma resposta; consultar uma vez reduziu 27 chamadas HTTP para 1. |
| Fallback em cascata no agente redator | O sistema nunca deixa de produzir a comunicação: se o LLM falhar (chave ausente, cota, indisponibilidade), o gerador local assume mantendo a personalização. |
| Modo de demonstração com cenários controlados (`--demo`) | Garante que o fluxo completo e os diferentes tipos de mensagem possam ser demonstrados mesmo em um dia sem avisos ativos no INMET, sem alterar nenhum outro agente. |

---

## 3. Descrição dos Agentes Desenvolvidos

### 3.1. `DataCollectorAgent` (Coletor) — Etapa 1: coleta
* **Responsabilidade:** Consultar a API pública `https://apiprevmet3.inmet.gov.br/avisos/ativos` e devolver, para cada cidade/UF da carteira, o aviso de maior severidade vigente no dia.
* **Como funciona:** `_obter_avisos_hoje()` baixa uma única vez por execução a lista de avisos do dia e a mantém em cache. `_consultar_avisos_inmet()` localiza o município dentro do campo `"municipios"` retornado pela API (busca por `"Cidade - UF"`) e, havendo mais de um aviso, seleciona o de maior `id_severidade`.
* Como a API descreve os riscos em texto livre (ex.: *"Chuva entre 20 e 30 mm/h... ventos intensos (40-60 km/h)"*), o método `_extrair_metricas_dos_riscos()` usa expressões regulares para extrair estimativas conservadoras (piores valores) de chuva (mm/h) e vento (km/h), além de detectar menção a granizo.
* Quando não há aviso ativo para a cidade, o clima é considerado estável (0 mm de chuva, vento baixo) e nenhuma comunicação é disparada.

### 3.2. `DemoDataCollectorAgent` (Coletor de demonstração)
* **Responsabilidade:** Substituir a fonte externa por cenários climáticos controlados descritos em `cenarios_demo.json`, acionado por `python main.py --demo`.
* Herda de `DataCollectorAgent` e respeita exatamente o mesmo contrato de saída, de modo que **nenhum outro agente do pipeline precisa saber se os dados vieram do INMET ou da demonstração**.
* Motivação: em dias sem avisos ativos no país, uma execução real não produziria nenhuma notificação; o modo demonstração garante a reprodutibilidade da avaliação e cobre os quatro tipos de evento e os três tipos de apólice.

### 3.3. `WeatherAnalyzerAgent` (Analisador) — Etapa 2: identificação de eventos
* **Responsabilidade:** Transformar as métricas brutas em eventos de risco qualitativos e em um nível de severidade (`BAIXO`, `ALTO`, `CRITICO`).
* **Regras implementadas e critério de definição:** os limiares foram definidos a partir da própria terminologia dos avisos do INMET e do impacto típico sobre bens segurados.

| # | Condição | Evento identificado | Severidade |
| --- | --- | --- | --- |
| 1 | Chuva ≥ 30 mm/h | Alagamento / Enxurrada | CRÍTICO |
| 1 | Chuva ≥ 15 mm/h | Chuva Forte | ALTO |
| 2 | Vento ≥ 60 km/h | Ciclone / Vendaval Forte | CRÍTICO |
| 2 | Vento ≥ 40 km/h | Ventos Fortes | ALTO |
| 3 | Menção a granizo no aviso oficial | Queda de Granizo | ALTO |
| 4 | Chuva ≥ 40 mm/h em município com ocupação relevante em encostas | Risco Altíssimo de Deslizamento | CRÍTICO |

### 3.4. `BusinessRulesAgent` (Decisor) — Etapa 3: regras de negócio
* **Responsabilidade:** Cruzar os eventos identificados com a geografia, o tipo de apólice (`Residencial`, `Empresarial`, `Automóvel`) e os `detalhes_seguro` de cada segurado, filtrando apenas quem reside na cidade afetada e cuja cobertura faz sentido para o risco.
* **Filtro geográfico:** o segurado só é considerado se residir na cidade do evento.
* **Regras de cruzamento evento × apólice:**

| Evento | Perfis notificados | Motivo registrado |
| --- | --- | --- |
| Alagamento / Enxurrada | Residencial, Empresarial | Risco de inundação do imóvel segurado. |
| Alagamento / Enxurrada | Automóvel **apenas se** o cadastro indicar que não possui garagem coberta | Risco de alagamento do veículo que estaciona em via pública. |
| Queda de Granizo | Automóvel | Risco de avarias na lataria e vidros. |
| Queda de Granizo | Residencial | Risco de quebra de telhados e vidraças. |
| Ventos Fortes / Vendaval | Residencial, Empresarial | Risco de destelhamento e danos estruturais. |
| Ventos Fortes / Vendaval | Automóvel | Risco de queda de galhos/árvores sobre o veículo. |
| Deslizamento | Residencial e Empresarial cujo cadastro mencione encosta, morro, ladeira ou serra | Alerta máximo de evacuação preventiva e proteção de vidas. |

* Quando um mesmo aviso dispara mais de uma regra (por exemplo, tempestade com vendaval **e** granizo), **todos** os motivos são acumulados e repassados ao agente redator, para que a mensagem reflita o quadro completo de risco.
* O agente devolve um payload unificado: os dados do segurado acrescidos de um `contexto_alerta` com eventos, severidade, motivo da regra e as medições climáticas.

### 3.5. `MessageGeneratorAgent` (Redator) — Etapa 4: geração com IA
* **Responsabilidade:** Redigir a notificação final, personalizada para o segurado e para o risco identificado.
* **Seleção do motor (`--provider`):**
  * `auto` (padrão) — detecta automaticamente a credencial disponível no `.env`: usa **Google Gemini** (`gemini-3.6-flash`) se houver `GEMINI_API_KEY`, **OpenAI** (`gpt-4o-mini`) se houver `OPENAI_API_KEY`, e o gerador local caso não haja nenhuma;
  * `gemini` / `openai` — força o provedor;
  * `simulation` — força o gerador local de templates, útil para execuções offline e para os testes automatizados.
* **Resiliência:** quando a API responde `429` (limite de requisições por minuto do plano gratuito), o agente aguarda e repete a chamada com espera progressiva (4s, 10s, 20s); se o modelo não estiver habilitado na conta, tenta automaticamente os modelos alternativos da lista. Esgotadas as tentativas, a falha é registrada em log e a mensagem é produzida pelo gerador local **mantendo a personalização** do segurado — o segurado nunca fica sem comunicação.
* **Rastreabilidade da origem:** cada notificação registra o motor que **de fato** a redigiu (`gemini-3.6-flash`, `gpt-4o-mini` ou `template-local`), e não apenas o motor configurado. O resumo da execução exibe a contagem por motor, de modo que é sempre possível auditar quais mensagens saíram do LLM e quais saíram do gerador local.
* **Engenharia de prompt.** O prompt é montado em duas partes:

  * **System prompt (persona e diretrizes de escrita):**
    > *"Você é a inteligência proativa de uma Seguradora de alta confiabilidade. Seu tom deve ser empático, urgente mas não alarmista, e focado em segurança física e material. Gere uma mensagem curta, estruturada em tópicos curtos de prevenção, direta e personalizada, evitando termos burocráticos ou robóticos."*

  * **User prompt (contexto dinâmico injetado a cada segurado):** nome, cidade, eventos climáticos identificados, nível de severidade, tipo e detalhes da apólice, motivo da regra de negócio que o tornou elegível e as medições de chuva (mm/h) e vento (km/h). O modelo é instruído a produzir **3 passos curtos de prevenção específicos para o tipo de seguro** e a informar a disponibilidade da assistência 24h.

### 3.6. `NotificationSimulator` e `carregar_base_segurados` — Etapa 5: simulação do envio
* `carregar_base_segurados()` carrega a carteira de `segurados.json` (27 registros, um por unidade federativa), recriando o arquivo com um registro mínimo caso ele não exista.
* `NotificationSimulator` imprime no console o "disparo" da notificação — destinatário, e-mail, telefone, cidade/UF, tipo de seguro, severidade, motor que redigiu a mensagem e o corpo da comunicação —, simulando o canal multicanal (e-mail/SMS/WhatsApp) sem integração real de envio, e devolve o registro estruturado da notificação.
* Com a opção `--salvar`, o pipeline consolida todas as notificações da execução em `saida/notificacoes_<data>.json`, servindo de evidência auditável do que foi gerado.

---

## 4. Tecnologias Utilizadas

* **Linguagem:** Python 3.12+.
* **Orquestração de Agentes:** implementação própria, sem framework externo (5 classes de agentes + funções utilitárias em `main.py`).
* **API Meteorológica:** API pública de avisos ativos do INMET (`https://apiprevmet3.inmet.gov.br/avisos/ativos`), sem necessidade de chave.
* **API de IA Generativa:** Google Gemini (`gemini-3.6-flash`) ou OpenAI (`gpt-4o-mini`), com fallback automático para o gerador local de templates.
* **Bibliotecas Python:**
  * `requests` — consumo da API do INMET;
  * `google-genai` e `openai` — integração com os LLMs;
  * `python-dotenv` — carregamento de `GEMINI_API_KEY` / `OPENAI_API_KEY` a partir do `.env`;
  * `argparse` e `unittest` (biblioteca padrão) — interface de linha de comando e testes.
* **Persistência:** `segurados.json` (carteira, 27 registros) e `cenarios_demo.json` (cenários controlados de demonstração).
* **Segurança de credenciais:** chaves lidas exclusivamente de variáveis de ambiente; `.env` no `.gitignore` e `.env.example` versionado como modelo.
* **Interface de Demonstração:** CLI com saída formatada no console.

---

## 5. Fluxo de Processamento Ponta a Ponta

1. `carregar_base_segurados()` lê `segurados.json` e retorna a lista de segurados (ou `carregar_cenarios_demo()` no modo `--demo`).
2. O pipeline deriva dinamicamente a lista de cidades/UF a monitorar a partir dos pares únicos `(cidade, uf)` presentes na carteira — nenhuma cidade da base fica de fora da análise.
3. **Coleta:** `DataCollectorAgent.coletar_dados(cidade, uf)` consulta a API do INMET e retorna as métricas climáticas (ou "clima estável" se não houver aviso ativo).
4. **Análise:** `WeatherAnalyzerAgent.analisar_risco(...)` classifica os eventos de risco e o nível de severidade.
5. **Decisão:** `BusinessRulesAgent.determinar_elegibilidade(...)` filtra, dentro da carteira, os segurados elegíveis para receber o alerta e anexa o contexto do risco.
6. **Geração:** para cada segurado elegível, `MessageGeneratorAgent.gerar_comunicacao_preventiva(...)` redige a mensagem personalizada com o LLM (ou com o gerador local).
7. **Envio simulado:** `NotificationSimulator.enviar(...)` imprime o disparo no console e devolve o registro da notificação.
8. Ao final, o pipeline exibe o resumo da execução (fonte de dados, motor de geração, cidades monitoradas, cidades com evento e total de comunicações) e, com `--salvar`, grava tudo em `saida/`.

### 5.1. Como reproduzir

```bash
pip install -r requirements.txt

python main.py                  # execução real, com os avisos vigentes do INMET
python main.py --demo --salvar  # demonstração completa e reprodutível, com evidência em saida/
python -m unittest discover -s tests -v   # 30 testes automatizados
```

---

## 6. Exemplos de Mensagens Geradas

Todos os textos desta seção foram capturados em execuções reais do sistema, sem edição. Cada exemplo indica o motor que efetivamente o redigiu, conforme registrado pelo próprio pipeline.

### 6.1. Mensagem redigida pelo LLM — Rio Branco/AC (Seguro Residencial)

* **Execução:** `python main.py` em 13/09/2026, com o aviso oficial do INMET vigente no momento.
* **Aviso oficial do INMET:** Chuvas Intensas — Perigo Potencial.
* **Eventos identificados:** Alagamento / Enxurrada, Ciclone / Vendaval Forte — severidade **CRITICO**.
* **Segurado:** Lucas Silva — casa térrea no bairro Bosque, Rio Branco/AC.
* **Regra de negócio acionada:** Risco de inundação do imóvel segurado devido a volume de chuva crítico. Risco de destelhamento e danos estruturais no imóvel.
* **Mensagem redigida por:** Google Gemini (`gemini-flash-latest`).

```text
**Alerta de Segurança: Chuva forte e vendaval em Rio Branco**

Olá, Lucas. Identificamos um risco crítico de alagamento e ventos fortes (60 km/h) nas próximas horas para a sua região no bairro Bosque.

Como a sua casa é térrea, sua segurança e a proteção do seu lar são nossa prioridade imediata. Por favor, tome estas precauções agora:

* **Eleve bens e eletrônicos:** Retire móveis e eletrodomésticos das áreas mais baixas e desconecte aparelhos da tomada para evitar queimas por oscilação na rede.
* **Feche e trave acessos:** Tranque portas, janelas e verifique se entradas de ar estão vedadas para reduzir a força do vento e a entrada de água.
* **Proteja documentos e busque abrigo:** Mantenha itens importantes em sacos plásticos em local alto e seguro. Evite ficar próximo a janelas ou sob telhados frágeis.

Estamos com você nesse momento. Se houver qualquer emergência ou necessidade de reparo, nossa **Assistência 24h está pronta para te atender pelo aplicativo ou pelo telefone 0800 [inserir número]**.

Fique em segurança.
```

Observe que o modelo incorporou dados que só existem no cadastro do segurado (casa térrea, bairro Bosque) e nas medições extraídas do aviso do INMET (ventos de 60 km/h), produzindo recomendações específicas para aquela apólice — e não um texto genérico.

### 6.2. Cenário controlado — Chuva intensa com risco de alagamento — Recife/PE (Seguro Residencial)

* **Segurado:** Helena Moreira (helena.moreira@email.com / +55 81 98100-0901)
* **Eventos identificados:** Alagamento / Enxurrada — severidade **CRITICO**
* **Regra de negócio acionada:** Risco de inundação do imóvel segurado devido a volume de chuva crítico.
* **Mensagem redigida por:** Google Gemini (`gemini-flash-latest`)

```text
**Alerta de Emergência: Risco Crítico de Alagamento**

Olá, Helena. Nossos sistemas meteorológicos identificaram chuvas intensas em Recife (35 mm/h) com risco imediato de alagamento para a sua região em Afogados. 

A sua segurança e a proteção do seu lar são nossa prioridade agora. Como sua casa é térrea, pedimos que tome estas medidas preventivas imediatamente:

* **Desligue a chave geral de energia:** Evite curtos-circuitos e garanta a segurança de todos caso a água comece a subir.
* **Eleve móveis e eletrodomésticos:** Coloque itens de valor e aparelhos eletrônicos sobre suportes, mesas ou em locais mais altos.
* **Instale barreiras e vede acessos:** Use sacos de areia ou comportas nas portas de entrada e ralos para conter ou atrasar a entrada da água.

Lembre-se: sua apólice Residencial conta com cobertura completa para danos elétricos e por água. Não se arrisque por bens materiais.

Estamos com você. Se precisar de qualquer apoio de emergência, nossa **Assistência 24h está pronta para te atender pelo app ou no telefone 0800-XXX-XXXX.** 

Fique em segurança.
```

### 6.3. Cenário controlado — Chuva intensa — Recife/PE (Seguro Automóvel sem garagem coberta)

* **Segurado:** Sabrina Peixoto (sabrina.peixoto@email.com / +55 81 98100-0903)
* **Eventos identificados:** Alagamento / Enxurrada — severidade **CRITICO**
* **Regra de negócio acionada:** Risco de alagamento do veículo que estaciona em via pública.
* **Mensagem redigida por:** gerador local de templates

```text
🚨 *ALERTA DE PREVENÇÃO PROATIVA - ALAGAMENTO / ENXURRADA*

Olá, *Sabrina Peixoto*!
Nossos sistemas de monitoramento identificaram risco iminente de *Alagamento / Enxurrada* na região de *Recife*.
Identificamos que sua apólice de *Seguro Automóvel* possui o seguinte cenário: Risco de alagamento do veículo que estaciona em via pública.

Como sua segurança vem sempre em primeiro lugar, recomendamos tomar os seguintes cuidados imediatamente:
🔹 *1.* Busque estacionar seu veículo em garagens cobertas ou locais elevados e seguros.
🔹 *2.* Evite estacionar abaixo de árvores, postes, redes elétricas ou painéis de publicidade.
🔹 *3.* Evite trafegar por vias com histórico conhecido de alagamento ou baixa visibilidade.

Estamos acompanhando as condições meteorológicas em tempo real. Se precisar de socorro ou assistência 24h, estamos prontos no WhatsApp ou fone 0800-123-4567. Conte conosco! 🤝
```

### 6.4. Cenário controlado — Tempestade com granizo — Curitiba/PR (Seguro Automóvel)

* **Segurado:** Ricardo Menezes (ricardo.menezes@email.com / +55 41 98200-0904)
* **Eventos identificados:** Chuva Forte, Ventos Fortes, Queda de Granizo — severidade **ALTO**
* **Regra de negócio acionada:** Risco de avarias na lataria e vidros do veículo segurado. Alto risco de queda de galhos/árvores sobre o veículo estacionado.
* **Mensagem redigida por:** Google Gemini (`gemini-flash-latest`)

```text
**Alerta Meteorológico: Cuidado com seu veículo nas próximas horas**

Olá, Ricardo. 

Identificamos a aproximação imediata de fortes chuvas (18mm/h), ventos de 45km/h e alto risco de **queda de granizo** em Curitiba. 

Como a prioridade é a sua segurança e a preservação do seu SUV (placa CWB-0904), recomendamos alguns cuidados rápidos para evitar danos à lataria e aos vidros:

* **Procure abrigo coberto:** Estacione seu veículo em garagem coberta ou estacionamento subterrâneo o quanto antes.
* **Evite árvores e postes:** Não deixe o carro estacionado próximo a galhos, árvores ou fiações que possam cair com a força do vento.
* **Espere a tempestade passar:** Se estiver dirigindo no momento da chuva de granizo, reduza a velocidade e busque um local seguro para parar (como um posto de combustível). Evite trafegar com visibilidade reduzida.

Estamos monitorando a situação e ao seu lado para o que precisar. Se houver qualquer imprevisto, nossa **Assistência 24h** está pronta para te atender diretamente pelo aplicativo ou pelo telefone de emergência. 

Fique seguro!
```

### 6.5. Cenário controlado — Vendaval costeiro — Florianópolis/SC (Seguro Empresarial)

* **Segurado:** Marcos Bittencourt (marcos.bittencourt@email.com / +55 48 98300-0906)
* **Eventos identificados:** Ciclone / Vendaval Forte — severidade **CRITICO**
* **Regra de negócio acionada:** Risco de destelhamento e danos estruturais no imóvel.
* **Mensagem redigida por:** Google Gemini (`gemini-flash-latest`)

```text
**Alerta de Segurança Climática | Atenção Imediata**

Olá, **Marcos**. 

Identificamos a aproximação de um ciclone com ventos fortes de **75 km/h** em Florianópolis nas próximas horas. Por estar à beira-mar em Canasvieiras, sua pousada está em uma área de maior exposição a rajadas intensas, com risco de destelhamento e impactos na estrutura.

A segurança dos seus hóspedes, da sua equipe e do seu patrimônio é nossa prioridade. Por favor, adote estas medidas preventivas agora:

* **Proteja aberturas e coberturas:** Tranque bem todas as portas e janelas externas (especialmente as voltadas para o mar) e verifique se há telhas ou estruturas leves soltas.
* **Recolha a mobília externa:** Retire ou amarre firmemente mesas, cadeiras de praia, guarda-sóis e ombrelones para evitar que sejam arremessados pelo vento.
* **Oriente os hóspedes e isole áreas abertas:** Peça que permaneçam nos quartos, longe de janelas de vidro, e suspenda o uso de áreas comuns abertas ou próximas a árvores.

Sua apólice cobre vendaval e destelhamento, e nós estamos com você para garantir que tudo fique bem. 

Se precisar de qualquer suporte de emergência, nossa **Assistência 24h** já está de prontidão. Basta acionar pelo app ou ligar para o nosso canal direto. 

Cuide-se e proteja os seus. Estamos ao seu lado.
```

### 6.6. Cenário controlado — Risco de deslizamento — Rio de Janeiro/RJ (Seguro Residencial em encosta)

* **Segurado:** Jorge Nascimento (jorge.nascimento@email.com / +55 21 98400-0908)
* **Eventos identificados:** Alagamento / Enxurrada, Risco Altíssimo de Deslizamento — severidade **CRITICO**
* **Regra de negócio acionada:** Risco de inundação do imóvel segurado devido a volume de chuva crítico. Alerta máximo de evacuação preventiva e proteção de vidas.
* **Mensagem redigida por:** gerador local de templates

```text
🚨 *ALERTA DE PREVENÇÃO PROATIVA - ALAGAMENTO / ENXURRADA*

Olá, *Jorge Nascimento*!
Nossos sistemas de monitoramento identificaram risco iminente de *Alagamento / Enxurrada, Risco Altíssimo de Deslizamento* na região de *Rio de Janeiro*.
Identificamos que sua apólice de *Seguro Residencial* possui o seguinte cenário: Risco de inundação do imóvel segurado devido a volume de chuva crítico. Alerta máximo de evacuação preventiva e proteção de vidas.

Como sua segurança vem sempre em primeiro lugar, recomendamos tomar os seguintes cuidados imediatamente:
🔹 *1.* Mantenha ralos, calhas e condutores limpos para evitar o acúmulo de água no telhado.
🔹 *2.* Retire eletrodomésticos sensíveis das tomadas para prevenir queimas devido a descargas elétricas.
🔹 *3.* Mantenha portas e janelas fechadas e evite proximidade com vidraças durante vendavais.

Estamos acompanhando as condições meteorológicas em tempo real. Se precisar de socorro ou assistência 24h, estamos prontos no WhatsApp ou fone 0800-123-4567. Conte conosco! 🤝
```

### 6.7. Contraexemplo — Fortaleza/CE

O cenário de Fortaleza/CE foi propositalmente configurado sem evento climático relevante. O `WeatherAnalyzerAgent` não identifica nenhum evento, o `BusinessRulesAgent` não retorna segurados elegíveis e **nenhuma notificação é gerada** — comprovando que a solução não dispara comunicações desnecessárias.

### 6.8. Execuções registradas

| Indicador | Execução com dados reais | Execução em modo demonstração |
| --- | --- | --- |
| Fonte dos dados | API de avisos do INMET | `cenarios_demo.json` |
| Cidades monitoradas | 27 (uma por segurado da carteira) | 5 |
| Cidades com evento relevante | 6 | 4 |
| Notificações geradas | 5 | 9 |
| Requisições à API do INMET | 1 para todo o país | não se aplica |

Cada execução pode ser registrada em disco com a opção `--salvar`, que grava em `saida/notificacoes_<data>.json` o texto de todas as notificações, a regra de negócio que tornou cada segurado elegível e o motor que redigiu a mensagem.

> **Nota sobre a cota do LLM.** Os cenários 6.2 a 6.6 acima foram capturados em uma execução na qual a cota diária gratuita da API do Gemini já havia se esgotado. O pipeline então exerceu exatamente o comportamento de resiliência projetado: após três falhas consecutivas, desligou o provedor de IA, redigiu as mensagens restantes com o gerador local e **reportou corretamente a origem de cada texto**. Com cota disponível, as mesmas mensagens são redigidas pelo LLM, como no exemplo 6.1.
---

## 7. Validação e Testes

A suíte automatizada (`python -m unittest discover -s tests -v`) executa **30 testes**, sem depender de rede nem de chave de API, cobrindo:

* **Agente Coletor:** extração de chuva/vento/granizo do texto livre dos avisos do INMET, tolerância a textos sem métricas e uso efetivo do cache.
* **Agente Analisador:** cada um dos limiares de severidade e a restrição geográfica da regra de deslizamento.
* **Agente Decisor:** filtro por cidade, elegibilidade por tipo de apólice, a exceção do seguro Automóvel sem garagem coberta, a exigência de imóvel em encosta para o alerta de deslizamento e o conteúdo do `contexto_alerta`.
* **Agente Redator:** personalização por nome/cidade, presença de exatamente três recomendações preventivas, diferenciação das recomendações por tipo de seguro e preservação da personalização no fallback do LLM.
* **Simulador de envio** e **integridade das bases** (`segurados.json` e `cenarios_demo.json`).
* **Pipeline ponta a ponta** em modo de demonstração, verificando que os três perfis de apólice e os quatro tipos de evento são exercitados e que uma cidade sem evento não gera notificação.

---

## 8. Conclusão e Próximos Passos

O MVP demonstra a viabilidade técnica de um fluxo ponta a ponta totalmente automatizado — da consulta a uma fonte meteorológica oficial em tempo real até a redação, por IA generativa, de uma mensagem preventiva personalizada — sem exigir nenhuma chave de API paga para o núcleo do sistema (o INMET é público e gratuito). A geração com LLM é plugável, detectada automaticamente a partir do ambiente, e conta com fallback local que garante que a comunicação nunca deixe de ser produzida.

**Melhorias sugeridas para um ambiente produtivo:**
* Substituir o `NotificationSimulator` por integrações reais de envio (e-mail transacional, SMS, WhatsApp Business API), com controle de opt-in e horário de contato.
* Persistir o histórico de alertas e notificações em banco de dados, evitando reenvios duplicados para o mesmo evento e permitindo medir a efetividade da prevenção.
* Enriquecer a carteira com geolocalização (latitude/longitude) para substituir o casamento por nome de município por uma verificação de área de abrangência do aviso.
* Agendar a execução periódica (cron/serverless) em vez da execução manual, com fila de disparo.
* Evoluir a arquitetura para um framework de agentes (LangChain/LangGraph) caso seja necessário raciocínio multi-passo ou uso de ferramentas pelos próprios agentes.
