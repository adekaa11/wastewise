-- Пароли в базе — только хэши. Сохранить пароль открытым текстом база не даст (даже по ошибке в коде).
-- Допустимы два вида:
--   pbkdf2$<соль, 32 hex>$<хэш, 64 hex> — PBKDF2-SHA256 с солью (core/db.py → hash_password);
--   <64 hex>                          — старый sha256 без соли из версии 1, при первом входе
--                                       заменяется на PBKDF2 (core/db.py → authenticate).
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'users_password_is_hash') THEN
        ALTER TABLE users ADD CONSTRAINT users_password_is_hash
            CHECK (password ~ '^(pbkdf2\$[0-9a-f]{32}\$[0-9a-f]{64}|[0-9a-f]{64})$');
    END IF;
END $$;
