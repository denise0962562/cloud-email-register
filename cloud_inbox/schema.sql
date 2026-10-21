CREATE TABLE IF NOT EXISTS hme_public_inboxes (
  id TEXT PRIMARY KEY,
  alias TEXT NOT NULL UNIQUE,
  token_hash TEXT NOT NULL,
  api_token TEXT NOT NULL,
  destination TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
