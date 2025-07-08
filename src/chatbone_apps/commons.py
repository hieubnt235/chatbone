CHATBONE_ASSISTANT_APP_PREFIX = "<Chatbone_Assistant>"
CHATBONE_ASSISTANT_APP_POSTFIX = "<Chatbone_Assistant>"

def _make_deployment_name_from_real_import_path(real_import_path :str):
    return f"{CHATBONE_ASSISTANT_APP_PREFIX}{real_import_path}{CHATBONE_ASSISTANT_APP_POSTFIX}"

