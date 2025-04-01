# Test performance if async loop is high load
import time
import asyncio
import aiohttp
import multiprocessing as mp
import threading
import os
import aiofiles

async def load1():
    await asyncio.sleep(1)

async  def load2():
    async with aiohttp.ClientSession() as session:
        async with session.get('https://python.langchain.com/docs/versions/migrating_memory/chat_history/#use-with-langgraph') as response:
            await response.text()

async def load3():
    async with aiofiles.open('./a.txt', mode='r') as file:
        await file.read()


def info():
    return f"PID[{os.getpid()}] - [{threading.get_native_id()}] "


async def main(n):
    s = time.time()
    tasks = [load3() for _ in range(n) ]
    print(f"Time for create {n} tasks: {time.time()-s}")
    s = time.time()

    await asyncio.gather(*tasks)
    print(f"Execution time for {n} tasks: {time.time()-s}.")
    print("==========================================================")


def c(n,d):
    return main(int(n/d))

if __name__=="__main__":

    n=100000
    start = time.time()
    asyncio.run(main(n))
    all_t = time.time()-start

    d =8 # n threads
    # print(type(main(n/2)))

    t_class = mp.Process

    threads = []

    start = time.time()
    for i in range(d):
        thread = t_class(target=asyncio.run,args=(c(n,d),))
        threads.append(thread)
        threads[-1].start()

    print(f"Created threads in {time.time()-start}")

    for thread in threads:
        thread.join()

    t_t = time.time()-start
    print(f"Done in total:{t_t}")
    print(f"Boost: {all_t/t_t}")


# how to distribute and get back the result
# param n,d