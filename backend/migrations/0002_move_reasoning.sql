-- Why a move was made: agent explanations and timeout notes. NULL for human moves.
ALTER TABLE moves ADD COLUMN reasoning text;
