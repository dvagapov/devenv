FROM python:3.12-alpine3.20

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app/src

WORKDIR /app

# Create non-root runtime user.
RUN addgroup -S app && adduser -S -G app app

COPY requirements.txt ./
RUN apk add --no-cache --virtual .build-deps build-base linux-headers \
    && python -m pip install --upgrade pip \
    && pip install -r requirements.txt \
    && apk del .build-deps

COPY src ./src

USER app

CMD ["python", "-m", "log_analyzer.main"]
