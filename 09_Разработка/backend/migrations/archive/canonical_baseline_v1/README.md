# Архив canonical baseline v1

Здесь хранится неизменяемая историческая цепочка из 31 Alembic revision,
заменённая активным корнем `canonical_baseline_v1`.

Файлы в `revisions/` не входят в active `version_locations`, не исполняются
Alembic и не должны редактироваться. Их имена, размеры, revision metadata и
SHA-256 зафиксированы в
`migrations/baselines/canonical_baseline_v1/frozen-revision-manifest.json`.

Новые migrations создаются только поверх активного
`migrations/versions/canonical_baseline_v1.py`.
