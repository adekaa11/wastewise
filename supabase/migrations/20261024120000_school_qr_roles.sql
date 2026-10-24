-- WasteWise v2: роли (ученик / учитель / админ) и QR-режим школьных экобоксов.
-- Те же изменения для локального SQLite — core/db.py → init_db. Повторный запуск безопасен.

-- ---------- Роли и класс пользователя ----------
-- role: student — по умолчанию; teacher видит отчёт своей школы (school_id); admin — все школы.
-- Роль назначается только вручную (python -m core.roles или SQL ниже) — сам себе её никто не поставит.
ALTER TABLE users ADD COLUMN IF NOT EXISTS role TEXT NOT NULL DEFAULT 'student';
ALTER TABLE users ADD COLUMN IF NOT EXISTS school_id TEXT;            -- код школы, как в QR: nis_astana
ALTER TABLE users ADD COLUMN IF NOT EXISTS class_label TEXT NOT NULL DEFAULT '';  -- «7А»: для отчёта учителя
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'users_role_valid') THEN
        ALTER TABLE users ADD CONSTRAINT users_role_valid CHECK (role IN ('student', 'teacher', 'admin'));
    END IF;
END $$;

-- ---------- QR-режим: у какого бака какой школы сделано фото ----------
-- Ссылка в QR-коде на баке: ?school_id=nis_astana&box=plastic. «Ошибка у бака» — когда итоговый тип
-- (исправление пользователя или ответ модели) не совпадает с баком; считается при отчёте (core/report.py).
ALTER TABLE scans ADD COLUMN IF NOT EXISTS school_id TEXT;
ALTER TABLE scans ADD COLUMN IF NOT EXISTS bin TEXT;
ALTER TABLE scans ADD COLUMN IF NOT EXISTS class_label TEXT;           -- класс ученика на момент фото
CREATE INDEX IF NOT EXISTS idx_scans_school_date ON scans (school_id, date);

-- Назначить учителя (выполнить в Supabase → SQL Editor, подставив логин и код школы):
--   UPDATE users SET role = 'teacher', school_id = 'nis_astana' WHERE username = 'логин_учителя';
-- Назначить администратора:
--   UPDATE users SET role = 'admin' WHERE username = 'ваш_логин';
