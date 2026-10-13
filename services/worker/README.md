# Worker

O worker reutiliza o domínio da API: celery -A app.tasks.celery_app worker --beat --loglevel=info --concurrency=1.
Tasks mantêm locks Redis por fornecedor e avaliação de alertas. Coinbase não faz parte do agendamento automático inicial.
