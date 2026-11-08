-- How an agent produced a move: model, mode, retries, tool calls, tokens, seconds. NULL if none.
ALTER TABLE moves ADD COLUMN meta jsonb;
