# from chatbone_utils.tasks import repeat_n_times
#
# repeat_n_times.run(7)
import time
import aiohttp
from threading import Thread



def main():
    t1 = Thread(target=foo,args=(5,))
    t2 = Thread(target=bar,args=(7,))
    t3 = Thread(target=foo,args=(3,))
    t1.start()
    t2.start()
    t3.start()

    t1.join()
    t2.join()
    t3.join()

if __name__=="__main__":
    main()