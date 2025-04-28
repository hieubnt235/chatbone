

from utilities import logger

marker = "chat"
def pytest_collection_modifyitems(config, items) -> None:

    assert isinstance(config,type(config))
    ids=[]
    for item in items:
        if f"{marker}/" in item.nodeid:
            item.add_marker(marker)
            ids.append(item.nodeid)
    logger.debug(f"\nMarked \'{marker}\' for {len(ids)} items:\n"
                 f"{"\n".join(ids)}")
