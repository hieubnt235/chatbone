import asyncio as aio
from sys import stdout
from threading import Thread

from langchain_huggingface import HuggingFacePipeline
from transformers import AsyncTextIteratorStreamer
from transformers import AutoModelForCausalLM, AutoTokenizer, pipeline, BitsAndBytesConfig
from transformers import Qwen2ForCausalLM, set_seed, TextGenerationPipeline


def setup():
	print("Setting up")
	set_seed(42)
	model_path = 'Qwen/Qwen2.5-1.5B-Instruct'
	quantization_cfg = BitsAndBytesConfig(load_in_8bit=True)
	tokenizer = AutoTokenizer.from_pretrained(model_path)
	model = AutoModelForCausalLM.from_pretrained(model_path, # torch_dtype=torch.bfloat16,
	                                             quantization_config=quantization_cfg, low_cpu_mem_usage=True)
	assert isinstance(model, Qwen2ForCausalLM)

	hf_pipe = pipeline(task='text-generation', model=model, tokenizer=tokenizer, device_map='auto', max_new_tokens=500)
	assert isinstance(hf_pipe, TextGenerationPipeline)
	lang_pipe = HuggingFacePipeline(pipeline=hf_pipe)

	from langchain_huggingface import ChatHuggingFace
	chat_model = ChatHuggingFace(llm=lang_pipe)

	from langchain_core.prompts import ChatPromptTemplate
	template = ChatPromptTemplate.from_messages(
		[('system', 'Answer and explain the question based on the context.'), ('human', 'Context: {context}'),
			('human', 'Question: {question}'), ])
	context = 'A 5 years old child is learning math and ask the question. Need to explain for the kid to understand.'
	question = 'what is 3+5 ?'
	ques_prompt = template.invoke(dict(context=context, question=question))
	return tokenizer, chat_model, ques_prompt


async def delay(t):
	while True:
		stdout.write('...')
		await aio.sleep(t)


async def main(t=0.5):
	tokenizer, chat_model, ques_prompt = setup()
	aistreamer = AsyncTextIteratorStreamer(tokenizer=tokenizer, skip_prompt=True, skip_special_tokens=True)
	thread = Thread(target=chat_model.invoke, args=(ques_prompt,),
		kwargs=dict(pipeline_kwargs=dict(return_full_text=False, top_k=1, streamer=aistreamer)))
	thread.start()
	print("Thread started")
	aio.create_task(delay(t))
	print("Delay task created")
	print("Start async for")
	async for text in aistreamer:
		# print(text,end="")
		stdout.write(text)
		stdout.flush()


if __name__ == '__main__':
	aio.run(main())
