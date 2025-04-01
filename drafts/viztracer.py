import os
import threading
import asyncio
import time


def cpu_bound():
    time.sleep(1)

def info():
    return f"PID[{os.getpid()}] - [{threading.get_native_id()}] "

async def foo(n):
    for i in range(5):
        print(f"{info()}foo {n} step: {i + 1} ")
        cpu_bound()
        await asyncio.sleep(0.5)


async def main(n):
    task1 = asyncio.create_task(foo(n), name=f'foo {n}-task {info()}')
    asyncio.current_task().set_name(f"main-task {info()}")q
    for i in range(5):
        print(f"{info()}main {n} step: {i + 1} ")
        cpu_bound()
        await asyncio.sleep(0.5)
    await task1



if __name__=="__main__":
    print(f"{info()}Entrypoint")
    t1 = threading.Thread(target=asyncio.run,args=(main(1),))
    t2 = threading.Thread(target=asyncio.run,args=(main(2),))
    t1.start()
    t2.start()
    print("thread started")
    t1.join()
    t2.join()