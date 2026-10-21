CREATE TABLE IF NOT EXISTS attachment_assets (
    attachment_id TEXT NOT NULL REFERENCES attachments(id),
    asset_id TEXT NOT NULL,
    position INTEGER NOT NULL,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    size INTEGER,
    source_path TEXT NOT NULL DEFAULT '',
    thumbnail_path TEXT NOT NULL DEFAULT '',
    preview_path TEXT NOT NULL DEFAULT '',
    state TEXT NOT NULL DEFAULT 'indexed',
    observation TEXT NOT NULL DEFAULT '',
    detail TEXT NOT NULL DEFAULT '',
    error TEXT NOT NULL DEFAULT '',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY(attachment_id,asset_id)
);
CREATE INDEX IF NOT EXISTS idx_asset_progress ON attachment_assets(attachment_id,position);
CREATE TABLE IF NOT EXISTS attachment_overviews (
    attachment_id TEXT NOT NULL REFERENCES attachments(id),
    batch_id TEXT NOT NULL,
    asset_ids_json TEXT NOT NULL,
    sheet_path TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'pending',
    observation TEXT NOT NULL DEFAULT '',
    error TEXT NOT NULL DEFAULT '',
    PRIMARY KEY(attachment_id,batch_id)
);
