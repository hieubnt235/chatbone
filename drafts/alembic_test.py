rom alembic import context

config  context.config

a = config.config_ini_section
b = config.get_section(a)

print(a)
print(b)