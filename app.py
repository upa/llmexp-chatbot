import os
import json
import traceback
import hashlib
import base64
from pathlib import Path

import asyncio

from chainlit.types import ConnectSseMCPRequest
from mcp import ClientSession
from mcp.types import TextContent, ImageContent

from openai import AsyncAssistantEventHandler, AsyncAzureOpenAI, AzureOpenAI
from literalai.helper import utc_now

import chainlit as cl
from chainlit.config import config
import chainlit.data as cl_data
from chainlit.data.sql_alchemy import SQLAlchemyDataLayer

from chainlit.server import connect_mcp

from dotenv import load_dotenv
from openai.types.beta.threads.runs import RunStep

import logging

# ------ Logging ------
logger = logging.getLogger("llmexp-chatbot")
format = "%(asctime)s:%(levelname)s:%(funcName)s: %(message)s"
logging.basicConfig(level=logging.INFO, format=format)

# ------ Config & Env ------
load_dotenv(".env")


def load_instruction() -> str:
    md = Path(__file__).with_name("instruction.md")
    try:
        return md.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise RuntimeError(f"{md} not found")


instruction = load_instruction()


# ------ OpenAI Clients ------
async_client = AsyncAzureOpenAI(
    azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
    api_key=os.environ["AZURE_OPENAI_API_KEY"],
    api_version=os.environ["AZURE_OPENAI_API_VERSION"],
)

sync_openai_client = AzureOpenAI(
    azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
    api_key=os.environ["AZURE_OPENAI_API_KEY"],
    api_version=os.environ["AZURE_OPENAI_API_VERSION"],
)
assistant = sync_openai_client.beta.assistants.retrieve(
    os.environ["AZURE_OPENAI_ASSISTANT_ID"]
)


# ------ Chainlit Setup ------
ASSISTANT_NAME = "OAI-ShowNet Assistant"
config.ui.name = ASSISTANT_NAME
# set sqlite.db as a persistent storage
database_url = "sqlite+aiosqlite:///data/sqlite.db"
cl_data._data_layer = SQLAlchemyDataLayer(database_url)


# ------ Event Handler Class ------
class EventHandler(AsyncAssistantEventHandler):
    def __init__(self) -> None:
        super().__init__()

        # initialized by on_run_step_created
        self.run_id = "UNINITIALIZED_RUN_ID"
        self.thread_id = "UNINITIALIZED_THRETAD_ID"

        # initialized by on_text_created
        self.current_message: cl.Message | None = None
        self.current_search_step: cl.Step | None = None
        self.current_search_call = None

    async def on_run_step_created(self, run: RunStep):
        self.run_id = run.run_id
        self.thread_id = run.thread_id

    async def on_text_created(self, text) -> None:
        self.current_message = await cl.Message(
            author=ASSISTANT_NAME, content=""
        ).send()

    async def on_text_delta(self, delta, snapshot):
        if delta.value:
            await self.current_message.stream_token(delta.value)

    async def on_text_done(self, text):
        logger.info(f"on_text_done: {text}")
        await self.current_message.update()

    async def on_tool_call_created(self, tool_call):
        logger.info(f"on_tool_call_created: {tool_call}")

        # mcp_tool (tool_call.type == function) creates step by
        # submit_tool_outputs. Thus, crate step when type is
        # file_search.
        if tool_call.type == "file_search":
            self.current_search_call = tool_call.id
            self.current_search_step = cl.Step(name="file_search", type="tool")
            self.current_search_step.created_at = utc_now()
            await self.current_search_step.send()

    async def on_tool_call_delta(self, delta, snapshot):
        pass

    async def on_tool_call_done(self, tool_call):
        logger.info(f"on_tool_call_done: {tool_call}")

        if tool_call.type == "file_search":
            self.current_search_step.end = utc_now()
            await self.current_search_step.update()

        elif tool_call.type == "function":
            await self.on_tool_call_done_function()

    async def on_tool_call_done_function(self):
        while True:
            run = await async_client.beta.threads.runs.retrieve(
                thread_id=self.thread_id, run_id=self.run_id
            )
            logger.debug(f"run_id: {self.run_id}, check run.status: {run.status}")

            if run.status == "requires_action":
                tool_calls = run.required_action.submit_tool_outputs.tool_calls
                tool_outputs = []

                for tool_call in tool_calls:
                    if tool_call.type != "function":
                        continue

                    func_name = tool_call.function.name
                    func_args = json.loads(tool_call.function.arguments)
                    mcp_tools = cl.user_session.get("mcp_tools", {})
                    mcp_name = None
                    for connection_name, tools in mcp_tools.items():
                        if any(tool.get("name") == func_name for tool in tools):
                            mcp_name = connection_name
                            break

                    func_response = await call_tool(mcp_name, func_name, func_args)
                    logger.info(f"function response: {func_response}")

                    tool_outputs.append(
                        {
                            "tool_call_id": tool_call.id,
                            "output": func_response,
                        }
                    )

                logger.info(
                    "return tool_outputs for {}".format(
                        [t["tool_call_id"] for t in tool_outputs]
                    )
                )
                async with async_client.beta.threads.runs.submit_tool_outputs_stream(
                    thread_id=self.thread_id,
                    run_id=self.run_id,
                    tool_outputs=tool_outputs,
                    event_handler=EventHandler(),
                ) as stream:
                    await stream.until_done()

            elif run.status in ["completed", "failed", "cancelled", "expired"]:
                break

            await asyncio.sleep(1)


# ------ Chainlit Callbacks ------
@cl.on_chat_start
async def start_chat():
    # Create a Thread
    thread = await async_client.beta.threads.create()
    # Store thread ID in user session for later use
    cl.user_session.set("thread_id", thread.id)

    await connect_predefined_mcp_servers()


async def connect_predefined_mcp_servers():
    # Connect to MCP Servers predefined in the .env file
    # MCP server is defined as MCP_SERVER_[ANYWORD]=NAME@URL
    logger.info("connect MCP Sever!!")
    for key, name_and_url in os.environ.items():
        if key.startswith("MCP_SERVER_"):
            name, url = name_and_url.split("@")

            session_id = cl.user_session.get("id")
            logger.info(f"add MCP server {name} {url} to {session_id}")
            mcpreq = ConnectSseMCPRequest(
                sessionId=session_id, clientType="sse", name=name, url=url
            )
            try:
                await connect_mcp(mcpreq, None)
            except Exception as e:
                logger.error(e)
                msg = f"Failed to add MCP server {name} at {url}: {str(e)}"
                await cl.Message(msg).send()


def flatten(xss):
    return [x for xs in xss for x in xs]


@cl.on_message
async def main(message: cl.Message):
    thread_id = cl.user_session.get("thread_id")
    if not thread_id:
        raise RuntimeError("Empty Thread ID")

    default_settings: dict = {}
    mcp_tools = cl.user_session.get("mcp_tools", default_settings)
    tools = flatten([tools for _, tools in mcp_tools.items()])
    tools = [{"type": "function", "function": tool} for tool in tools]

    # check the user is not @interop-tokyo.net or @g.ecc.u-tokyo.ac.jp,
    # then remove the tool:
    # {
    #   "type": "function",
    #   "function": {"name" : "set_config_commands_and_commit_or_save"}
    # }
    # that can configure devices.
    user = cl.user_session.get("user")
    logger.info(f"user: {user}")
    if user and not (
        user.identifier.endswith("@interop-tokyo.net")
        or user.identifier.endswith("@g.ecc.u-tokyo.ac.jp")
    ):
        # remove send_command_and_get_output
        tools = [
            t
            for t in tools
            if not (
                t["type"] == "function"
                and t["function"]["name"] == "set_config_commands_and_commit_or_save"
            )
        ]
        logger.info(f"remove tool set_config for {user.identifier}")

    if not [t for t in tools if t["type"] == "file_search"]:
        # add file_search on Azure AI Assistant
        tools.append({"type": "file_search"})

    # logger.info(f"on_message: tools: {tools}")

    logger.info(f"on_message: {message.content}")

    # Add a Message to the Thread
    await async_client.beta.threads.messages.create(
        thread_id=thread_id,
        role="user",
        content=message.content,
    )

    # Create and Stream a Run
    async with async_client.beta.threads.runs.stream(
        thread_id=thread_id,
        assistant_id=assistant.id,
        event_handler=EventHandler(),
        tools=tools,
        instructions=instruction,
    ) as stream:
        await stream.until_done()


# ------ MCP Integration ------
@cl.on_mcp_connect
async def on_mcp_connect(connection, session: ClientSession):
    result = await session.list_tools()
    tools = [
        {
            "name": t.name,
            "description": t.description,
            "parameters": t.inputSchema,
        }
        for t in result.tools
    ]

    mcp_tools = cl.user_session.get("mcp_tools", {})
    mcp_tools[connection.name] = tools

    logger.info(
        "mcp_connect: {}".format(
            ", ".join([t["name"] for t in tools if isinstance(t["name"], str)])
        )
    )
    cl.user_session.set("mcp_tools", mcp_tools)


@cl.on_mcp_disconnect
async def on_mcp_disconnect(name: str, session: ClientSession):
    logger.warning(f"on_mcp_disconnect: {name}")


# ------ Tool Invocation ------
@cl.step(type="tool")
async def call_tool(mcp_name, function_name, function_args):
    resp_items = []
    try:
        logger.info(f"MCP:{mcp_name} Function:{function_name} Args:{function_args}")
        mcp_session = cl.context.session.mcp_sessions.get(mcp_name)
        if not mcp_session:
            msg = f"no MCP session for {mcp_name}"
            logger.error(msg)
            return msg
        func_response = await mcp_session.client.call_tool(function_name, function_args)
        for item in func_response.content:
            if isinstance(item, TextContent):
                resp_items.append(item.text)
            elif isinstance(item, ImageContent):
                resp_items.append(
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{item.mimeType};base64,{item.data}",
                        },
                    }
                )
            else:
                raise ValueError(f"Unsupported content type: {type(item)}")

    except Exception as e:
        traceback.print_exc()
        resp_items.append({"type": "text", "text": str(e)})
    return json.dumps(resp_items)


def validate_password(username: str, password: str) -> bool:
    #########################################
    #
    # Implement your authentication logic here.
    # Below is just a mock auth.
    usermap = {
        "user1": "user1 password here"
    }
    if username in usermap:
        return usermap[username] == password
    return False


@cl.password_auth_callback
def auth_callback(username: str, password: str):
    # Fetch the user matching username from your database
    # and compare the hashed password with the value stored in the database
    # TODO: Change the condition when we decide the admin user
    if validate_password(username, password):
        return cl.User(
            identifier=username,
            metadata={
                "role": "admin" if username == "admin@example.com" else "user",
                "provider": "credentials",
            },
        )
    else:
        return None


# starter
@cl.set_starters
async def set_starters():
    return [
        cl.Starter(
            label="例: 機器のシャーシの状態を確認してみる",
            message="Coreルータのうち、MXのシャーシの状態を確認、問題があれば報告して"

        ),
        cl.Starter(
            label="例: インターフェースの状態を確認してみる",
            message="ex4400.mgmtのインターフェースの状態を確認、descriptionと一緒にテーブルで表示"
        ),
        cl.Starter(
            label="例: 過去のShowNetの機器のconfigから設定例を聞いてみる",
            message="過去のShowNetのconfigから、nexusのEVPN-VXLANの設定例を表示して"
        ),
        cl.Starter(
            label="例: TTDBのチケットを参照してみる",
            message="チケットを確認して、バックボーンに関連するタスクをピックアップ"
        ),

    ]
