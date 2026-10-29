# Estado atual do Document Intelligence RAG

Revisão: 13/10/2026. Git inicial limpo. Etapa comprovada nesta revisão: leitura documental e de assinaturas/limites selecionados. Nenhum upload, `.env`, armazenamento privado ou banco foi lido; nenhuma aplicação, OCR, avaliação ou teste executado.

## Componentes observados e documentação prévia

[backend/app/main.py](../backend/app/main.py) reúne FastAPI, modelos, autenticação e armazenamento na construção `build_app`. Há módulos separados de extraction, retrieval, generation, security, store e worker. [retrieval.py](../backend/app/retrieval.py) declara tokenização, conceitos, embedding local, cosseno e busca; [generation.py](../backend/app/generation.py) declara resposta e verificação de citações. [security.py](../backend/app/security.py) define identidades, contenção de caminhos, validação de upload e limite de 10 MiB. São evidências estáticas, sem atestar todos os controles em runtime.

[README](../README.md) descreve OCR inglês/português, BM25, hashing vetorial de 384 dimensões, busca híbrida e SQLite/PostgreSQL com pgvector. O texto distingue hashing de embedding semântico treinado e resposta extrativa de inferência/aritmética/síntese multidocumento. Esses limites permanecem documentados. [frontend/package.json](../frontend/package.json) declara React/TypeScript/Vite e scripts dev/build/preview.

## Regras e evidências

[AGENTS](../AGENTS.md) exige documentos sintéticos/licenciados, proveniência de página/coordenadas, autorização no servidor antes de recuperação e arquivos de fonte, rejeição de respostas sem suporte e conteúdo recuperado tratado como dados. O seletor Viewer/Reviewer é demo; o README não o apresenta como autenticação de produção. O baseline público descrito não exige provider pago nem implementa geração remota nesta release.

Os resultados de 18 casos e QA no README/[validation](validation.md) são relatos anteriores, não testes aprovados por esta revisão. Arquivos de avaliações existem; não foram reexecutados. Não se copiou conteúdo de outros repositórios para a base.

## Operação

Consultar o [README](../README.md) para caminhos Windows/Docker, Python/Tesseract/Node e configuração. Foram identificados `python scripts/init_compose.py`, `docker compose up --build -d`, `run-demo.bat`, comando Uvicorn com `--app-dir backend`, `.venv/Scripts/python.exe -m pytest`, avaliação `evals/run.py --check` e `npm run build` em frontend. Todos: **não executado nesta tarefa**. Não se inicializou configuração, dependência ou banco.

## Roadmap e retomada

O README mantém como trabalho futuro OIDC, isolamento por usuário/tenant, auditoria, retenção, rotação de tokens e deployment de produção. Não foram transformados em requisitos aprovados ou funcionalidades implementadas. Sugestões: (1) escolher extração, recuperação ou interface para o próximo pedido; (2) revisar as evidências e avaliações existentes sem ampliar suas conclusões; (3) confirmar escopo próprio antes de autenticação/hosting. Nenhuma decisão histórica nova foi inventada.

[Índice](INDEX.md).
