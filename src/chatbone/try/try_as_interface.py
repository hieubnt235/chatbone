
from ray import serve
from utilities import logger
from chatbone.assistant_interface import AssistantInterface


@serve.deployment()
class FakeChatApp:

	async def __call__(self, *args, **kwargs):
		names = await AssistantInterface.get_assistant_names()
		for n in names:
			logger.info(repr(n))

chat_app = FakeChatApp.bind()