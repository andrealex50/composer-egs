with open('/home/andrealex/Payment_service/alembic/env.py', 'r') as f:
    text = f.read()

replacement = """import os
    config_section = config.get_section(config.config_ini_section, {})
    db_url = os.environ.get("DATABASE_URL")
    if db_url:
        config_section["sqlalchemy.url"] = db_url

    connectable = async_engine_from_config(
        config_section,
"""

text = text.replace('connectable = async_engine_from_config(\n        config.get_section(config.config_ini_section, {}),', replacement)

with open('/home/andrealex/Payment_service/alembic/env.py', 'w') as f:
    f.write(text)
