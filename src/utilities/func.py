import os
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo
from utilities.logger import logger
import psutil
from pwdlib import PasswordHash
from pathlib import Path

# Password utils
password_hash = PasswordHash.recommended()


def hash_password(password: str):
	hp  = password_hash.hash(password)
	return hp


def verify_password(password: str, hashed_password)->bool:
	return password_hash.verify(password, hashed_password)


def utc_now():
	return datetime.now(timezone.utc)


def cal_time_delta(dt1: datetime, dt2: datetime) -> timedelta:
	"""
	Returns: return dt2-dt1
	"""
	return dt2.astimezone(ZoneInfo("UTC")) - dt1.astimezone(ZoneInfo("UTC"))


class get_expire_date_factory:
	def __init__(self, duration_seconds: int = 43200):
		self.duration_seconds = duration_seconds

	def __call__(self):
		return datetime.now(tz=timezone.utc) + timedelta(seconds=self.duration_seconds)


def get_expire_date(duration_seconds: int = 43200) -> datetime:
	return datetime.now(tz=timezone.utc) + timedelta(seconds=duration_seconds)


def make_deleted_old_ids(objs: list[Any], max_objs: int, sort_key: str = "created_at", id_key="id") -> list:
	assert max_objs >= 0
	sorted_objs = sorted(objs, key=lambda obj: getattr(objs, sort_key))
	if max_objs == 0:
		# delete all
		objs_to_delete = sorted_objs
	else:
		objs_to_delete = sorted_objs[:-max_objs]
	ids = [getattr(obj, id_key) for obj in objs_to_delete]
	return ids


def check_is_subset(list1: list, list2: list, *, key1: str | None = None, key2: str | None = None) -> bool:
	"""
	Check if all elements in list1 appear in list2.
	If key is None, check element directly. Otherwise, the value of key will be extracted and checked.
	"""
	if key1 is not None:
		list1 = [getattr(e, key1) for e in list1]
	if key2 is not None:
		list2 = [getattr(e, key2) for e in list2]
	set1 = set(list1)
	set2 = set(list2)
	return set1.issubset(set2)


def get_process_stats(pid: int | None = None, recursive=False):
	try:
		pid = os.getpid() if pid is None else pid
		p = psutil.Process(pid)
		pp = p.parent()
		cp = p.children(recursive=recursive)

		return dict(main_info=f"pid:{p.pid} - name:{p.name()} - num_threads:{p.num_threads()}.",
			parent_info=f"pid:{pp.pid} - name:{pp.name()} - num_children:{len(pp.children(recursive))} - num_threads{pp.num_threads()}.",
			children_info=[
				f"pid:{c.pid} - name:{c.name()} - num_children:{len(c.children(recursive))} num_threads:{c.num_threads()}"
				for c in cp])

	except psutil.NoSuchProcess:
		return {"Error": f"Process with PID {pid} not found."}
	except psutil.AccessDenied:
		return {"Error": f"Access denied to process with PID {pid}. Try running as administrator/root."}
	except Exception as e:
		return {"Error": f"An unexpected error occurred for PID {pid}: {e}"}


def solve_relative_paths_recursively(data:dict, abs_path:Path):
	for k,v in data.items():
		if isinstance(v,dict):
			solve_relative_paths_recursively(v,abs_path)
		if isinstance(v,str) and k.endswith(("file","path","dir")):
			data[k] = (abs_path/Path(v)).resolve().as_posix()

# async def get_tasks(pid:int|None=None):
# 	ts = [t.get_coro().__qualname__ for t in asyncio.all_tasks()]
