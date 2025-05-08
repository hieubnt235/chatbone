import time

import executor


@executor
def repeat_n_times(n, t=1):
	for i in range(n):
		repeat_n_times.logger.warning(f"Repeat: {i + 1}")
		time.sleep(t)
