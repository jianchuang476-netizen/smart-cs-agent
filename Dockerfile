FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DEFAULT_TIMEOUT=120 \
    PIP_RETRIES=10

WORKDIR /app

COPY wheels/torch-2.9.1+cpu-cp312-cp312-manylinux_2_28_x86_64.whl /tmp/
RUN pip install --no-deps /tmp/torch-2.9.1+cpu-cp312-cp312-manylinux_2_28_x86_64.whl \
    && rm -f /tmp/torch-2.9.1+cpu-cp312-cp312-manylinux_2_28_x86_64.whl \
    && pip install filelock typing-extensions sympy networkx jinja2 fsspec setuptools \
        --index-url http://mirrors.aliyun.com/pypi/simple/ \
        --trusted-host mirrors.aliyun.com

COPY requirements.txt .
RUN pip install -r requirements.txt \
        --index-url http://mirrors.aliyun.com/pypi/simple/ \
        --trusted-host mirrors.aliyun.com

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
