import time

import torch
import torch.multiprocessing as mp
from torchvision.models import resnet18, ResNet18_Weights, resnet34, ResNet34_Weights


def model18():
	return resnet18(weights=ResNet18_Weights.IMAGENET1K_V1).cuda().eval()


def model34():
	return resnet34(weights=ResNet34_Weights.IMAGENET1K_V1).cuda().eval()


def infer(model):
	data = torch.zeros(16, 3, 224, 224).cuda()
	output = []
	for i in range(300):
		model(data)
		if i % 100 == 0:
			print(i, end=" ")
	print(f"Done")


if __name__ == "__main__":
	mp.set_start_method("spawn", force=True)
	# m = model()
	m1 = model18()
	m2 = model34()
	time.sleep(1)
	# print(m1==m2, m1==m)
	#
	p1 = mp.Process(target=infer, args=(m1,))
	p2 = mp.Process(target=infer, args=(m2,))
	print("Inited")

	print("sequential")
	start = time.time()
	infer(m1)
	print(time.time() - start)
	infer(m2)
	print(time.time() - start)
	print("Done sequential.....................")
	print()
	print("Parallel")
	startt = time.time()
	p1.start()
	p2.start()
	print("Started:", time.time() - startt)
	p1.join()
	p2.join()
	print(time.time() - startt)
	print("Done parallel.....................")
