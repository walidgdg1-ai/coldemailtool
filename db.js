const Database = require('better-sqlite3');
const path = require('path');
const fs = require('fs');
const { v4: uuidv4 } = require('uuid');
const { encrypt, decrypt } = require('./crypto-utils');

const DB_PATH = process.env.DB_PATH || path.join(__dirname, 'data.db');

const dbDir = path.dirname(DB_PATH);
if (!fs.existsSync(dbDir)) {
  fs.mkdirSync(dbDir, { recursive: true });
  console.log(`[DB] Created directory: ${dbDir}`);
}

const db = new Database(DB_PATH);
console.log(`[DB] Using database at: ${DB_PATH}`);

db.pragma('journal_mode = WAL');
db.pragma('foreign_keys = ON');

db.exec(`
  CREATE TABLE IF NOT EXISTS inboxes (
    id            TEXT PRIMARY KEY,
    email         TEXT UNIQUE NOT NULL,
    name          TEXT NOT NULL,
    access_token  TEXT,
    refresh_token TEXT NOT NULL,
    daily_limit   INTEGER DEFAULT 40,
    sent_today    INTEGER DEFAULT 0,
    last_reset    TEXT DEFAULT (date('now')),
    status        TEXT DEFAULT 'active',
    created_at    TEXT DEFAULT (datetime('now'))
  );

  CREATE TABLE IF NOT EXISTS campaigns (
    id                TEXT PRIMARY KEY,
    name              TEXT NOT NULL,
    status            TEXT DEFAULT 'draft',
    timezone          TEXT DEFAULT 'Europe/Paris',
    send_start_hour   INTEGER DEFAULT 8,
    send_end_hour     INTEGER DEFAULT 18,
    send_days         TEXT DEFAULT '1,2,3,4,5',
    track_opens       INTEGER DEFAULT 0,
    show_unsubscribe  INTEGER DEFAULT 0,
    unsubscribe_text  TEXT DEFAULT 'Unsubscribe',
    created_at        TEXT DEFAULT (datetime('now'))
  );

  CREATE TABLE IF NOT EXISTS campaign_steps (
    id          TEXT PRIMARY KEY,
    campaign_id TEXT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    step_number INTEGER NOT NULL,
    delay_days  INTEGER DEFAULT 0,
    UNIQUE(campaign_id, step_number)
  );

  CREATE TABLE IF NOT EXISTS step_variations (
    id      TEXT PRIMARY KEY,
    step_id TEXT NOT NULL REFERENCES campaign_steps(id) ON DELETE CASCADE,
    variant TEXT NOT NULL DEFAULT 'A',
    subject TEXT NOT NULL,
    body    TEXT NOT NULL,
    weight  INTEGER DEFAULT 1,
    UNIQUE(step_id, variant)
  );

  CREATE TABLE IF NOT EXISTS leads (
    id              TEXT PRIMARY KEY,
    campaign_id     TEXT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    email           TEXT NOT NULL,
    first_name      TEXT DEFAULT '',
    last_name       TEXT DEFAULT '',
    company         TEXT DEFAULT '',
    custom_data     TEXT DEFAULT '{}',
    status          TEXT DEFAULT 'pending',
    current_step    INTEGER DEFAULT 1,
    next_send_at    TEXT,
    assigned_inbox  TEXT,
    retry_count     INTEGER DEFAULT 0,
    unsubscribed    INTEGER DEFAULT 0,
    replied         INTEGER DEFAULT 0,
    replied_at      TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    UNIQUE(campaign_id, email)
  );

  CREATE TABLE IF NOT EXISTS email_logs (
    id          TEXT PRIMARY KEY,
    lead_id     TEXT NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
    campaign_id TEXT NOT NULL,
    step_number INTEGER NOT NULL,
    variant     TEXT DEFAULT 'A',
    inbox_id    TEXT NOT NULL,
    inbox_email TEXT NOT NULL,
    subject     TEXT NOT NULL,
    sent_at     TEXT DEFAULT (datetime('now')),
    status      TEXT DEFAULT 'sent',
    opened      INTEGER DEFAULT 0,
    opened_at   TEXT,
    open_count  INTEGER DEFAULT 0,
    clicked     INTEGER DEFAULT 0,
    error       TEXT
  );

  CREATE TABLE IF NOT EXISTS unsubscribes (
    id          TEXT PRIMARY KEY,
    lead_id     TEXT NOT NULL,
    campaign_id TEXT NOT NULL,
    email       TEXT NOT NULL UNIQUE,
    created_at  TEXT DEFAULT (datetime('now'))
  );
`);

function resetDailyCountsIfNeeded() {
  const today = new Date().toISOString().split('T')[0];
  db.prepare(`UPDATE inboxes SET sent_today = 0, last_reset = ? WHERE last_reset < ?`).run(today, today);
}

function getInboxes() {
  resetDailyCountsIfNeeded();
  return db.prepare(`SELECT id, email, name, daily_limit, sent_today, last_reset, status, created_at FROM inboxes ORDER BY created_at`).all();
}

function addInbox({ id, email, name, access_token, refresh_token, daily_limit }) {
  db.prepare(`
    INSERT INTO inboxes (id, email, name, access_token, refresh_token, daily_limit)
    VALUES (?, ?, ?, ?, ?, ?)
    ON CONFLICT(email) DO UPDATE SET
      access_token = excluded.access_token,
      refresh_token = excluded.refresh_token,
      name = excluded.name,
      daily_limit = excluded.daily_limit
  `).run(id, email, name, encrypt(access_token), encrypt(refresh_token), daily_limit || 40);
}

function getInboxWithTokens(id) {
  const inbox = db.prepare('SELECT * FROM inboxes WHERE id = ?').get(id);
  if (!inbox) return null;
  return { ...inbox, access_token: decrypt(inbox.access_token), refresh_token: decrypt(inbox.refresh_token) };
}

function updateInboxTokens(id, access_token) {
  db.prepare('UPDATE inboxes SET access_token = ? WHERE id = ?').run(encrypt(access_token), id);
}

function updateInbox(id, { name, daily_limit, status }) {
  const updates = [];
  const params = [];
  if (name !== undefined) { updates.push('name = ?'); params.push(name); }
  if (daily_limit !== undefined) { updates.push('daily_limit = ?'); params.push(daily_limit); }
  if (status !== undefined) { updates.push('status = ?'); params.push(status); }
  if (updates.length === 0) return;
  params.push(id);
  db.prepare(`UPDATE inboxes SET ${updates.join(', ')} WHERE id = ?`).run(...params);
}

function deleteInbox(id) { db.prepare('DELETE FROM inboxes WHERE id = ?').run(id); }

function incrementInboxSentCount(id) {
  resetDailyCountsIfNeeded();
  db.prepare('UPDATE inboxes SET sent_today = sent_today + 1 WHERE id = ?').run(id);
}

function pickBestInbox(leadId) {
  resetDailyCountsIfNeeded();
  if (leadId) {
    const assigned = db.prepare(`SELECT i.* FROM inboxes i JOIN leads l ON l.assigned_inbox = i.id WHERE l.id = ? AND i.status = 'active' AND i.sent_today < i.daily_limit`).get(leadId);
    if (assigned) return assigned;
  }
  return db.prepare(`SELECT * FROM inboxes WHERE status = 'active' AND sent_today < daily_limit AND daily_limit > 0 AND refresh_token IS NOT NULL ORDER BY (CAST(sent_today AS REAL) / MAX(daily_limit, 1)) ASC, RANDOM() LIMIT 1`).get();
}

function getCampaigns() {
  const campaigns = db.prepare('SELECT * FROM campaigns ORDER BY created_at DESC').all();
  const stmt = db.prepare(`SELECT COUNT(*) as total_leads, SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed, SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed, SUM(CASE WHEN replied = 1 THEN 1 ELSE 0 END) as replied, SUM(CASE WHEN unsubscribed = 1 THEN 1 ELSE 0 END) as unsubscribed FROM leads WHERE campaign_id = ?`);
  return campaigns.map(c => ({ ...c, stats: stmt.get(c.id) }));
}

function getCampaign(id) { return db.prepare('SELECT * FROM campaigns WHERE id = ?').get(id); }

function getCampaignSteps(campaignId) {
  const steps = db.prepare('SELECT * FROM campaign_steps WHERE campaign_id = ? ORDER BY step_number').all(campaignId);
  return steps.map(step => ({ ...step, variations: db.prepare('SELECT * FROM step_variations WHERE step_id = ? ORDER BY variant').all(step.id) }));
}

function createCampaign({ id, name, steps, timezone, send_start_hour, send_end_hour, send_days, track_opens, show_unsubscribe, unsubscribe_text }) {
  db.prepare(`INSERT INTO campaigns (id, name, timezone, send_start_hour, send_end_hour, send_days, track_opens, show_unsubscribe, unsubscribe_text) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`).run(id, name, timezone || 'Europe/Paris', send_start_hour ?? 8, send_end_hour ?? 18, send_days || '1,2,3,4,5', track_opens ? 1 : 0, show_unsubscribe ? 1 : 0, unsubscribe_text || 'Unsubscribe');
  if (steps && steps.length > 0) upsertSteps(id, steps);
}

function upsertSteps(campaignId, steps) {
  db.prepare('DELETE FROM campaign_steps WHERE campaign_id = ?').run(campaignId);
  const insertStep = db.prepare(`INSERT INTO campaign_steps (id, campaign_id, step_number, delay_days) VALUES (?, ?, ?, ?)`);
  const insertVariation = db.prepare(`INSERT INTO step_variations (id, step_id, variant, subject, body, weight) VALUES (?, ?, ?, ?, ?, ?)`);
  const tx = db.transaction((stepsData) => {
    for (let i = 0; i < stepsData.length; i++) {
      const step = stepsData[i];
      const stepId = uuidv4();
      insertStep.run(stepId, campaignId, i + 1, step.delay_days || 0);
      const variations = step.variations && step.variations.length > 0 ? step.variations : [{ variant: 'A', subject: step.subject || '', body: step.body || '', weight: 1 }];
      for (const v of variations) {
        if (!v.subject && !v.body) continue;
        insertVariation.run(uuidv4(), stepId, v.variant || 'A', v.subject || '', v.body || '', v.weight || 1);
      }
    }
  });
  tx(steps);
}

function updateCampaign(id, { name, status, steps, timezone, send_start_hour, send_end_hour, send_days, track_opens, show_unsubscribe, unsubscribe_text }) {
  const updates = []; const params = [];
  const fields = { name, status, timezone, send_start_hour, send_end_hour, send_days, unsubscribe_text };
  for (const [key, val] of Object.entries(fields)) { if (val !== undefined) { updates.push(`${key} = ?`); params.push(val); } }
  if (track_opens !== undefined) { updates.push('track_opens = ?'); params.push(track_opens ? 1 : 0); }
  if (show_unsubscribe !== undefined) { updates.push('show_unsubscribe = ?'); params.push(show_unsubscribe ? 1 : 0); }
  if (updates.length > 0) { params.push(id); db.prepare(`UPDATE campaigns SET ${updates.join(', ')} WHERE id = ?`).run(...params); }
  if (steps !== undefined) upsertSteps(id, steps);
}

function deleteCampaign(id) { db.prepare('DELETE FROM campaigns WHERE id = ?').run(id); }

function getCampaignStats(id) {
  return db.prepare(`SELECT COUNT(*) as total, SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) as pending, SUM(CASE WHEN status = 'active' THEN 1 ELSE 0 END) as active, SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed, SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed, SUM(CASE WHEN replied = 1 THEN 1 ELSE 0 END) as replied, SUM(CASE WHEN unsubscribed = 1 THEN 1 ELSE 0 END) as unsubscribed FROM leads WHERE campaign_id = ?`).get(id);
}

function pickVariation(stepId) {
  const variations = db.prepare('SELECT * FROM step_variations WHERE step_id = ?').all(stepId);
  if (variations.length === 0) return null;
  if (variations.length === 1) return variations[0];
  const totalWeight = variations.reduce((sum, v) => sum + (v.weight || 1), 0);
  let random = Math.random() * totalWeight;
  for (const v of variations) { random -= (v.weight || 1); if (random <= 0) return v; }
  return variations[0];
}

function getVariationStats(campaignId, stepNumber) {
  return db.prepare(`SELECT el.variant, COUNT(*) as sent, SUM(CASE WHEN el.opened = 1 THEN 1 ELSE 0 END) as opens, ROUND(100.0 * SUM(CASE WHEN el.opened = 1 THEN 1 ELSE 0 END) / MAX(COUNT(*), 1), 1) as open_rate, SUM(CASE WHEN el.status = 'replied' THEN 1 ELSE 0 END) as replies, ROUND(100.0 * SUM(CASE WHEN el.status = 'replied' THEN 1 ELSE 0 END) / MAX(COUNT(*), 1), 1) as reply_rate FROM email_logs el WHERE el.campaign_id = ? AND el.step_number = ? AND el.status NOT IN ('failed', 'sending') GROUP BY el.variant ORDER BY el.variant`).all(campaignId, stepNumber);
}

const DISPOSABLE_DOMAINS = new Set(['mailinator.com','guerrillamail.com','tempmail.com','throwaway.email','yopmail.com','guerrillamail.info','grr.la','sharklasers.com','guerrillamail.net','guerrillamail.de','trbvm.com','temp-mail.org','dispostable.com','trashmail.com','fakeinbox.com','mailnesia.com']);

function isValidEmailFormat(email) { return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email); }

function getLeads(campaignId, limit = 500, offset = 0) {
  return db.prepare(`SELECT * FROM leads WHERE campaign_id = ? ORDER BY created_at DESC LIMIT ? OFFSET ?`).all(campaignId, limit, offset);
}

function importLeads(campaignId, records) {
  const insert = db.prepare(`INSERT OR IGNORE INTO leads (id, campaign_id, email, first_name, last_name, company, custom_data) VALUES (?, ?, ?, ?, ?, ?, ?)`);
  const isUnsubscribed = db.prepare('SELECT 1 FROM unsubscribes WHERE email = ? LIMIT 1');
  const insertMany = db.transaction((rows) => {
    let added = 0;
    const skipped = { invalid: 0, disposable: 0, unsubscribed: 0, duplicate: 0 };
    for (const row of rows) {
      const email = (row.email || row.Email || row.EMAIL || '').trim().toLowerCase();
      if (!email || !isValidEmailFormat(email)) { skipped.invalid++; continue; }
      const domain = email.split('@')[1];
      if (DISPOSABLE_DOMAINS.has(domain)) { skipped.disposable++; continue; }
      if (isUnsubscribed.get(email)) { skipped.unsubscribed++; continue; }
      const custom = { ...row };
      ['email','Email','EMAIL','first_name','First_Name','firstName','last_name','Last_Name','lastName','company','Company'].forEach(k => delete custom[k]);
      const info = insert.run(uuidv4(), campaignId, email, row.first_name || row.firstName || row.First_Name || '', row.last_name || row.lastName || row.Last_Name || '', row.company || row.Company || '', JSON.stringify(custom));
      if (info.changes > 0) added++; else skipped.duplicate++;
    }
    return { added, skipped };
  });
  return insertMany(records);
}

function deleteLead(id) { db.prepare('DELETE FROM leads WHERE id = ?').run(id); }

function getDueLeads(limit = 20) {
  return db.prepare(`SELECT l.*, c.status as campaign_status, c.timezone, c.send_start_hour, c.send_end_hour, c.send_days, c.track_opens, c.show_unsubscribe, c.unsubscribe_text FROM leads l JOIN campaigns c ON c.id = l.campaign_id WHERE c.status = 'active' AND l.status IN ('pending', 'active') AND l.unsubscribed = 0 AND l.replied = 0 AND l.retry_count < 3 AND (l.next_send_at IS NULL OR l.next_send_at <= datetime('now')) ORDER BY l.next_send_at ASC NULLS FIRST LIMIT ?`).all(limit);
}

function getStep(campaignId, stepNumber) { return db.prepare('SELECT * FROM campaign_steps WHERE campaign_id = ? AND step_number = ?').get(campaignId, stepNumber); }

function getTotalSteps(campaignId) { const row = db.prepare('SELECT COUNT(*) as count FROM campaign_steps WHERE campaign_id = ?').get(campaignId); return row ? row.count : 0; }

function markLeadSent(leadId, nextStepNumber, totalSteps, delayDays, inboxId) {
  const isLast = nextStepNumber > totalSteps;
  const status = isLast ? 'completed' : 'active';
  const nextSendAt = isLast ? null : new Date(Date.now() + delayDays * 24 * 60 * 60 * 1000).toISOString();
  db.prepare(`UPDATE leads SET status = ?, current_step = ?, next_send_at = ?, assigned_inbox = ?, retry_count = 0 WHERE id = ?`).run(status, isLast ? nextStepNumber - 1 : nextStepNumber, nextSendAt, inboxId, leadId);
}

function markLeadFailed(leadId) { db.prepare(`UPDATE leads SET status = 'failed' WHERE id = ?`).run(leadId); }

function incrementLeadRetry(leadId) {
  const lead = db.prepare('SELECT retry_count FROM leads WHERE id = ?').get(leadId);
  if (!lead) return;
  const newCount = (lead.retry_count || 0) + 1;
  if (newCount >= 3) { db.prepare(`UPDATE leads SET status = 'failed', retry_count = ? WHERE id = ?`).run(newCount, leadId); }
  else { const backoffMs = 30 * 60 * 1000 * Math.pow(2, newCount - 1); const retryAt = new Date(Date.now() + backoffMs).toISOString(); db.prepare(`UPDATE leads SET retry_count = ?, next_send_at = ? WHERE id = ?`).run(newCount, retryAt, leadId); }
}

function markLeadReplied(leadIdOrEmail) {
  const lead = db.prepare('SELECT * FROM leads WHERE id = ? OR email = ? LIMIT 1').get(leadIdOrEmail, leadIdOrEmail);
  if (!lead) return { found: false };
  const now = new Date().toISOString();
  const result = db.prepare(`UPDATE leads SET replied = 1, replied_at = COALESCE(replied_at, ?), status = 'completed', next_send_at = NULL WHERE email = ? AND replied = 0`).run(now, lead.email);
  db.prepare(`UPDATE email_logs SET status = 'replied' WHERE id = (SELECT id FROM email_logs WHERE lead_id IN (SELECT id FROM leads WHERE email = ?) ORDER BY sent_at DESC LIMIT 1)`).run(lead.email);
  return { found: true, email: lead.email, updated: result.changes };
}

function hasLeadReplied(leadId) { const row = db.prepare('SELECT replied FROM leads WHERE id = ?').get(leadId); return row ? !!row.replied : false; }

function markEmailOpened(logId) { db.prepare(`UPDATE email_logs SET opened = 1, opened_at = COALESCE(opened_at, datetime('now')), open_count = open_count + 1 WHERE id = ?`).run(logId); }

function unsubscribeLead(leadId) {
  const lead = db.prepare('SELECT * FROM leads WHERE id = ?').get(leadId);
  if (!lead) return { found: false };
  db.prepare(`INSERT OR IGNORE INTO unsubscribes (id, lead_id, campaign_id, email) VALUES (?, ?, ?, ?)`).run(uuidv4(), leadId, lead.campaign_id, lead.email);
  db.prepare(`UPDATE leads SET unsubscribed = 1, status = 'unsubscribed', next_send_at = NULL WHERE email = ?`).run(lead.email);
  return { found: true, email: lead.email };
}

function isEmailUnsubscribed(email) { return !!db.prepare('SELECT 1 FROM unsubscribes WHERE email = ? LIMIT 1').get(email); }

function logEmail({ id, leadId, campaignId, stepNumber, variant, inboxId, inboxEmail, subject, status, error }) {
  db.prepare(`INSERT INTO email_logs (id, lead_id, campaign_id, step_number, variant, inbox_id, inbox_email, subject, status, error) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`).run(id, leadId, campaignId, stepNumber, variant || 'A', inboxId, inboxEmail, subject, status || 'sent', error || null);
}

function updateLogStatus(logId, status, subject, error) {
  const updates = ['status = ?']; const params = [status];
  if (subject !== undefined && subject !== null) { updates.push('subject = ?'); params.push(subject); }
  if (error !== undefined && error !== null) { updates.push('error = ?'); params.push(error); }
  params.push(logId);
  db.prepare(`UPDATE email_logs SET ${updates.join(', ')} WHERE id = ?`).run(...params);
}

function getCampaignLogs(campaignId, limit = 200) {
  return db.prepare(`SELECT el.*, l.email as lead_email, l.first_name, l.last_name, l.replied FROM email_logs el JOIN leads l ON l.id = el.lead_id WHERE el.campaign_id = ? ORDER BY el.sent_at DESC LIMIT ?`).all(campaignId, limit);
}

function getDashboardStats() {
  const inboxStats = db.prepare(`SELECT COUNT(*) as total, SUM(sent_today) as sent_today FROM inboxes WHERE status = 'active'`).get();
  const campaignStats = db.prepare(`SELECT COUNT(*) as total, SUM(CASE WHEN status = 'active' THEN 1 ELSE 0 END) as active FROM campaigns`).get();
  const leadStats = db.prepare(`SELECT COUNT(*) as total, SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed, SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed, SUM(CASE WHEN replied = 1 THEN 1 ELSE 0 END) as replied, SUM(CASE WHEN unsubscribed = 1 THEN 1 ELSE 0 END) as unsubscribed FROM leads`).get();
  const sentToday = db.prepare(`SELECT COUNT(*) as count FROM email_logs WHERE date(sent_at) = date('now') AND status = 'sent'`).get();
  const sentWeek = db.prepare(`SELECT COUNT(*) as count FROM email_logs WHERE sent_at >= datetime('now', '-7 days') AND status = 'sent'`).get();
  const recentLogs = db.prepare(`SELECT el.*, l.email as lead_email, l.replied, c.name as campaign_name FROM email_logs el JOIN leads l ON l.id = el.lead_id JOIN campaigns c ON c.id = el.campaign_id ORDER BY el.sent_at DESC LIMIT 10`).all();
  return { inboxStats, campaignStats, leadStats, sentToday: sentToday.count, sentWeek: sentWeek.count, recentLogs };
}

module.exports = {
  getInboxes, addInbox, getInboxWithTokens, updateInboxTokens, updateInbox, deleteInbox, incrementInboxSentCount, pickBestInbox,
  getCampaigns, getCampaign, getCampaignSteps, createCampaign, updateCampaign, deleteCampaign, getCampaignStats,
  pickVariation, getVariationStats,
  getLeads, importLeads, deleteLead,
  getDueLeads, getStep, getTotalSteps, markLeadSent, markLeadFailed, incrementLeadRetry,
  markLeadReplied, hasLeadReplied,
  markEmailOpened,
  unsubscribeLead, isEmailUnsubscribed,
  logEmail, updateLogStatus, getCampaignLogs,
  getDashboardStats,
};
