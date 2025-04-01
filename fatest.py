import time
from typing import Annotated

from fastapi import FastAPI, Depends

app = FastAPI()

def Dep():
    i =0
    while True:
        print(i)
        i+=1
        time.sleep(0.5)
        if i >100:
            break
    return i

@app.get("/dep")
async def abc():
    i = 0
    while True:
        print(i)
        i += 1
        time.sleep(0.5)
        if i > 100:
            break
    return {"abc":i}

@app.get("/")
async def get():
    return {"state":"still work"}

if __name__=="__main__":
    import uvicorn
    uvicorn.run("fatest:configs")