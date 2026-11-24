FROM litellm/litellm-database:v1.110.3
WORKDIR /app
COPY --chmod=755 bin/models /app/bin/models
COPY bin/models.py bin/model_catalog.py bin/catalog.json /app/bin/
ENV LLM_STACK_CONTAINER=1
