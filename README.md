# How to run:
pip install -r bot/requirements.txt
#
Set up variables BOT_TOKEN, POSTGRES_PASSWORD AND REDIS_PASSWORD in .env_dev. After copy these variables in your environment.
#
make
#
make dev
#
These commands launched 3 docker containers: telegram bot, postgres and redis.You have to stop the bot docker container and launch the bot with python
