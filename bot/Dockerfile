FROM python:3.11.5

RUN apt update && apt install -y netcat-traditional && rm -rf /var/lib/apt/lists/*


WORKDIR /bot

COPY . .
RUN pip --no-cache-dir install --upgrade pip setuptools
RUN pip --no-cache-dir install -r requirements.txt

