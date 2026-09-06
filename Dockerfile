FROM public.ecr.aws/lambda/python:3.12

COPY pyproject.toml uv.lock ./
RUN pip install --no-cache-dir uv boto3 \
    && uv export --frozen --no-dev -o requirements.txt \
    && pip install --no-cache-dir -r requirements.txt

COPY agent/lambda_handler.py ${LAMBDA_TASK_ROOT}/agent/lambda_handler.py

CMD ["agent.lambda_handler.handler"]
