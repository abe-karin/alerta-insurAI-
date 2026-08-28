# Ferramenta Inteligente para Comunicação Proativa com o Segurado (Desafio 5)

Este repositório contém o protótipo funcional (MVP) de uma solução inteligente de comunicação preventiva para seguradoras. O sistema consulta em tempo real a API pública de avisos ativos do INMET (Instituto Nacional de Meteorologia), analisa os riscos climáticos vigentes para cada cidade da carteira de segurados e utiliza Inteligência Artificial/LLMs (ou um gerador local de templates, como fallback) para redigir notificações personalizadas e preventivas antes que um sinistro ocorra.

---

## 🚀 Como Executar o Projeto

### Pré-requisitos
Antes de iniciar, certifique-se de ter instalado em sua máquina:
* **Python 3.12+**
* Gerenciador de pacotes **pip**
* Conexão com a internet (para consultar a API pública do INMET e, opcionalmente, a OpenAI/Gemini)
* (Opcional) Uma chave de API de LLM, caso queira gerar as mensagens com IA real em vez do gerador local de templates

### 1. Clonar o Repositório
```bash
git clone https://github.com/abe-karin/desafio5.git
cd desafio5
```

### 2. Configurar o Ambiente Virtual
Recomendamos o uso de um ambiente virtual para isolar as dependências do projeto:
```bash
# Criar o ambiente virtual
python -m venv venv

# Ativar o ambiente virtual
# No Windows:
venv\Scripts\activate
# No Linux/macOS:
source venv/bin/activate
```

### 3. Instalar Dependências
Instale todas as bibliotecas necessárias declaradas no arquivo de requisitos:
```bash
pip install -r requirements.txt
```

### 4. Configurar as Variáveis de Ambiente (opcional)
A API de avisos do INMET é pública e não exige chave. As variáveis abaixo só são necessárias
se você quiser que o `MessageGeneratorAgent` gere as mensagens com um LLM real em vez do
gerador local de templates. Crie um arquivo `.env` na raiz do projeto:
```bash
# Exemplo de arquivo .env
OPENAI_API_KEY=sua_chave_da_openai
GEMINI_API_KEY=sua_chave_do_google_gemini
```
> **⚠️ Importante:** Nunca envie o arquivo `.env` para o GitHub. Ele já está listado no `.gitignore` para garantir a segurança de suas credenciais.

### 5. Configurar a Carteira de Segurados
A carteira de segurados fica em `segurados.json`, na raiz do projeto. Caso o arquivo não
exista, ele é criado automaticamente com um registro de exemplo na primeira execução.

### 6. Executar a Aplicação
Execute o script principal para rodar a simulação ponta a ponta diretamente no terminal:
```bash
python main.py
```
O pipeline varre todas as cidades presentes em `segurados.json`, consulta os avisos oficiais
do INMET e imprime no console cada notificação preventiva gerada.

---

## 🛠️ Tecnologias Utilizadas

* **Linguagem:** Python 3.12+
* **Orquestração de Agentes:** implementação própria (4 classes de agentes em `main.py`)
* **Modelos de Linguagem (LLM):** OpenAI (`gpt-4o-mini`) ou Google Gemini (`gemini-1.5-flash`), com fallback automático para um gerador local de templates quando nenhuma chave é configurada
* **API Meteorológica:** API pública de avisos ativos do INMET (`https://apiprevmet3.inmet.gov.br/avisos/ativos`)
* **Interface de Demonstração:** CLI (saída formatada diretamente no terminal)

---

## 📦 Estrutura do Código-Fonte

```text
├── main.py                        # Ponto de entrada e todos os agentes (Coletor, Analisador, Decisor, Redator)
├── segurados.json                 # Carteira de segurados (gerada automaticamente se não existir)
├── requirements.txt                # Lista de dependências do Python
├── .env                            # Variáveis de ambiente opcionais (chaves de LLM), não versionado
├── relatorio-tecnico.md   # Template do relatório técnico do desafio
└── README.md                       # Instruções de instalação e documentação do projeto
```

Dentro de `main.py`, o pipeline é composto por:
* `carregar_base_segurados()` — carrega/inicializa `segurados.json`
* `DataCollectorAgent` — consulta os avisos ativos do INMET para cada cidade/UF
* `WeatherAnalyzerAgent` — classifica o risco (Alagamento, Vendaval, Granizo, Deslizamento, etc.)
* `BusinessRulesAgent` — cruza o risco identificado com o tipo de apólice de cada segurado
* `MessageGeneratorAgent` — redige a notificação (via OpenAI, Gemini ou template local)
* `NotificationSimulator` — imprime a notificação final simulando o disparo multicanal

---

## 📜 Licença

Este projeto está licenciado sob a **Licença MIT** - consulte o arquivo [LICENSE](LICENSE) para mais detalhes.

```text
MIT License

Copyright (c) 2026 [ InsurAi / Juan David Valle Sánchez, Rodrigo Silva Figueiredo, 
Isabela Del Rio, Karin Abe]

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
