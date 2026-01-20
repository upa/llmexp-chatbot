
# LLMexp Chatbot 

This repository contains a public version of LLM-based chatbot
implementation used for our experiment at Interop Tokyo 2025 ShowNet:
How Helpful is LLM Assistance in Network Operations?

The chatbot relies on
[Chainlit](https://docs.chainlit.io/get-started/overview) that
provides a common chat interface and connects it to an LLM.

We used [Azure OpenAI
Service](https://learn.microsoft.com/en-us/azure/ai-foundry/quickstarts/get-started-code?view=foundry-classic&tabs=python)
as the back-end LLM. Before running the chatbot, prepare an LLM model
deployed on the Azure Open AI Service. Note that the current
implementation uses Assistants API, so please select the models
capable of the Assistant API.

Also, the chatbot can use [Azure OpenAI Assistant file search
tool](https://learn.microsoft.com/en-us/azure/ai-foundry/openai/how-to/file-search?view=foundry-classic&tabs=python)
as a RAG data store. You can create a vector data store, upload your
files, and specify the vector store ID via the .env file.

Additionally, the chatbot implementation supports connecting to MCP servers.


## How to build and run the chatbot

* Install [uv](https://docs.astral.sh/uv/getting-started/installation/) first.

```shell
git clone git@github.com:upa/llmexp-chatbot
cd llmexp-chatbot

# install n (node and npm version manager)
curl -L https://bit.ly/n-install | bash
exec $SHELL -l

# install pnpm (package manager for building custom chainlit app)
npm install -g pnpm@latest
pnpm -v

# setup venv via uv
uv sync
source .venv/bin/activate

# setup a sqlite database to keep chat histories
mkdir -p data
sqlite3 ./data/sqlite.db < scheme.sql

# prepare .env file, see below.
vim .env
```

* Prepare `.env` file:

```dotenv
AZURE_OPENAI_ENDPOINT=[Azure OpenAI Endpoint URL]
AZURE_OPENAI_API_KEY=[API KEY associated with the above URL]
AZURE_OPENAI_MODEL=gpt-4.1
AZURE_OPENAI_API_VERSION=2024-12-01-preview

AZURE_VECTOR_STORE_ID=[Azure OpenAI Vector Store ID]
AZURE_OPENAI_ASSISTANT_ID=[Azure OpenAI Assistant ID]

# run `chainlit create-secret` to generate CHAINLIT_AUTH_SECRET
CHAINLIT_AUTH_SECRET=[Auth Secret]

# MCP Server URL (SSE)
#MCP_SERVER_NETMIKO="netmiko server@http://localhost:10000/sse"
#MCP_SERVER_TICKET="ttdb@http://localhost:20000/sse"
```

When a chat thread starts, the chatbot automatically connects to MCP
servers defined as `MCP_.*=[NAME]@[URL]` variables in the `.env`
file. [mcp-netmiko-server](https://github.com/upa/mcp-netmiko-server)
enables the chatbot to access CLIs of network devices.


* Run the chatbot

```shell
# Run chat UI (watch and debug mode)
chainlit run app.py -wdh
2026-01-20 15:24:55 - Loaded .env file
2026-01-20 15:24:57 - HTTP Request: GET [ENDPOINT URL] "HTTP/1.1 200 OK"
2026-01-20 15:24:57 - SQLAlchemyDataLayer storage client is not initialized and elements will not be persisted!
2026-01-20 15:24:57 - Created default chainlit markdown file at /Users/upa/work/code/llmexp-chatbot/chainlit.md
INFO:     Started server process [5009]
INFO:     Waiting for application startup.
2026-01-20 15:24:57 - Your app is available at http://localhost:8000
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
```

User authentication is not included, pelase see `validate_password()` in app.py.
