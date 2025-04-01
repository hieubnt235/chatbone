from datetime import datetime,timedelta, timezone
from zoneinfo import ZoneInfo
def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)

def cal_time_delta(dt1:datetime, dt2:datetime)->timedelta:
    """
    Returns: return dt2-dt1
    """
    return dt2.astimezone(ZoneInfo("UTC")) - dt1.astimezone(ZoneInfo("UTC"))

def get_expire_date(duration_seconds:int=86400) -> datetime:
    date = datetime.now(tz=timezone.utc) + timedelta(seconds=duration_seconds)
    return date.replace(tzinfo=None)