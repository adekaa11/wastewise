-- Фото «Модель ошиблась» — наш датасет: где лежит фото в Supabase Storage (core/storage.py).
-- Раскладка в бакете: feedback/<метка пользователя>/<md5 фото>.jpg.
ALTER TABLE scans ADD COLUMN IF NOT EXISTS feedback_path TEXT;

-- Приватный бакет feedback. Таблица storage.buckets есть только в Supabase, в обычном Postgres
-- (локально, в CI) этот шаг пропускается. Если прав не хватит, сайт создаст бакет сам через
-- Storage API при первом фото (тоже приватным) — поэтому ошибка здесь не останавливает миграцию.
DO $$
BEGIN
    IF to_regclass('storage.buckets') IS NOT NULL THEN
        BEGIN
            INSERT INTO storage.buckets (id, name, public) VALUES ('feedback', 'feedback', false)
            ON CONFLICT (id) DO NOTHING;
        EXCEPTION WHEN insufficient_privilege THEN
            RAISE NOTICE 'Нет прав создать бакет feedback через SQL — его создаст сайт (см. docs/SUPABASE.md)';
        END;
    END IF;
END $$;
