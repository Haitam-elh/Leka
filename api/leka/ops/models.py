"""Operations owns no table (LEKA-408), on purpose: what it keeps — the
alerts firing, the circuit breakers, the last backup's date — lives in Redis,
which forgetting costs at most an alert told twice; what it reads is every
other module's (repository.py).
"""
