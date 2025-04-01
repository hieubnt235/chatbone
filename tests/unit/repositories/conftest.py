

from chatbone import logger

marker = "repo"
def pytest_collection_modifyitems(config, items) -> None:

    assert isinstance(config,type(config))
    ids=[]
    for item in items:
        if f"repositories/" in item.nodeid:
            item.add_marker(marker)
            ids.append(item.nodeid)
    logger.debug(f"\nMarked \'{marker}\' for {len(ids)} items:\n"
                 f"{"\n".join(ids)}")
