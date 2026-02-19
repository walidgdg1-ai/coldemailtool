require('dotenv').config();
const express = require('express');
const cors = require('cors');
const multer = require('multer');
const { parse } = require('csv-parse/sync');
const { v4: uuidv4 } = require('uuid');
const path = require('path');
const db = require('./db');
const gmail = require('./gmail');
const scheduler = require('./scheduler');

const app = express();
app.set('trust proxy', 1);

const CORS_ORIGIN = process.env.CORS_ORIGIN || '';
if (CORS_ORIGIN) { app.use(cors({ origin: CORS_ORIGIN })); }
else if (process.env.NODE_ENV !== 'production') { app.use(cors()); }

const upload = multer({ storage: multer.memoryStorage(), limits: { fileSize: 50 * 1024 * 1024 } });
app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));

app.get('/api/health', (req, res) => {
  res.json({ ok: true, scheduler: process.env.RUN_SCHEDULER !== 'false', env: { clientId: !!process.env.GMAIL_CLIENT_ID, clientSecret: !!process.env.GMAIL_CLIENT_SECRET, redirectUri: process.env.GMAIL_REDIRECT_URI || 'http://localhost:3000/auth/callback', baseUrl: process.env.BASE_URL || 'http://localhost:3000', encryption: !!process.env.ENCRYPTION_KEY, dbPath: process.env.DB_PATH || './data.db' }});
});

app.get('/auth/callback', async (req, res) => {
  const { code, state, error } = req.query;
  if (error) return res.redirect(`/?error=${encodeURIComponent(error)}`);
  try {
    let name = '', daily_limit = 40;
    try { const parsed = JSON.parse(Buffer.from(state, 'base64').toString()); name = parsed.name || ''; daily_limit = parsed.daily_limit || 40; } catch {}
    const { tokens, email } = await gmail.exchangeCode(code);
    db.addInbox({ id: uuidv4(), email, name: name || email, access_token: tokens.access_token, refresh_token: tokens.refresh_token, daily_limit });
    res.redirect('/?tab=inboxes&success=Inbox+added+successfully');
  } catch (e) { console.error('OAuth callback error:', e.message); res.redirect(`/?error=${encodeURIComponent(e.message)}`); }
});

app.get('/api/inboxes', (req, res) => { res.json(db.getInboxes()); });
app.post('/api/inboxes/auth-url', (req, res) => {
  if (!process.env.GMAIL_CLIENT_ID || !process.env.GMAIL_CLIENT_SECRET) return res.status(400).json({ error: 'GMAIL_CLIENT_ID and GMAIL_CLIENT_SECRET must be set' });
  const { name, daily_limit } = req.body;
  const state = Buffer.from(JSON.stringify({ name, daily_limit: daily_limit || 40 })).toString('base64');
  res.json({ url: gmail.getAuthUrl(state) });
});
app.patch('/api/inboxes/:id', (req, res) => { db.updateInbox(req.params.id, req.body); res.json({ ok: true }); });
app.delete('/api/inboxes/:id', (req, res) => { db.deleteInbox(req.params.id); res.json({ ok: true }); });

app.get('/api/campaigns', (req, res) => { res.json(db.getCampaigns()); });
app.post('/api/campaigns', (req, res) => {
  const { name, steps, timezone, send_start_hour, send_end_hour, send_days, track_opens, show_unsubscribe, unsubscribe_text } = req.body;
  if (!name) return res.status(400).json({ error: 'name is required' });
  const id = uuidv4();
  db.createCampaign({ id, name, steps: steps || [], timezone: timezone || 'Europe/Paris', send_start_hour: send_start_hour ?? 8, send_end_hour: send_end_hour ?? 18, send_days: send_days || '1,2,3,4,5', track_opens: !!track_opens, show_unsubscribe: !!show_unsubscribe, unsubscribe_text: unsubscribe_text || 'Unsubscribe' });
  res.json({ id });
});
app.get('/api/campaigns/:id', (req, res) => {
  const campaign = db.getCampaign(req.params.id);
  if (!campaign) return res.status(404).json({ error: 'Not found' });
  res.json({ ...campaign, steps: db.getCampaignSteps(req.params.id), stats: db.getCampaignStats(req.params.id) });
});
app.put('/api/campaigns/:id', (req, res) => {
  const { name, steps, status, timezone, send_start_hour, send_end_hour, send_days, track_opens, show_unsubscribe, unsubscribe_text } = req.body;
  db.updateCampaign(req.params.id, { name, status, steps, timezone, send_start_hour, send_end_hour, send_days, track_opens, show_unsubscribe, unsubscribe_text });
  res.json({ ok: true });
});
app.delete('/api/campaigns/:id', (req, res) => { db.deleteCampaign(req.params.id); res.json({ ok: true }); });

app.get('/api/campaigns/:id/ab-stats', (req, res) => {
  const steps = db.getCampaignSteps(req.params.id);
  res.json(steps.map(step => ({ step_number: step.step_number, delay_days: step.delay_days, variations: db.getVariationStats(req.params.id, step.step_number) })));
});

app.get('/api/campaigns/:id/leads', (req, res) => { res.json(db.getLeads(req.params.id, parseInt(req.query.limit) || 500, parseInt(req.query.offset) || 0)); });
app.post('/api/campaigns/:id/leads/import', upload.single('file'), (req, res) => {
  if (!req.file) return res.status(400).json({ error: 'No file uploaded' });
  try { const records = parse(req.file.buffer.toString('utf-8'), { columns: true, skip_empty_lines: true, trim: true }); const { added, skipped } = db.importLeads(req.params.id, records); res.json({ added, total: records.length, skipped }); }
  catch (e) { res.status(400).json({ error: e.message }); }
});
app.delete('/api/campaigns/:campaignId/leads/:leadId', (req, res) => { db.deleteLead(req.params.leadId); res.json({ ok: true }); });

app.post('/api/leads/:id/replied', (req, res) => { const result = db.markLeadReplied(req.params.id); if (!result.found) return res.status(404).json({ error: 'Lead not found' }); res.json({ ok: true, email: result.email, leadsUpdated: result.updated, message: `All follow-ups stopped for ${result.email}` }); });
app.post('/api/leads/replied', (req, res) => { const { email } = req.body; if (!email) return res.status(400).json({ error: 'email is required' }); const result = db.markLeadReplied(email.trim().toLowerCase()); if (!result.found) return res.status(404).json({ error: 'Lead not found' }); res.json({ ok: true, email: result.email, leadsUpdated: result.updated, message: `All follow-ups stopped for ${result.email}` }); });

app.get('/t/:logId', (req, res) => { try { db.markEmailOpened(req.params.logId); } catch (e) {} const pixel = Buffer.from('R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7', 'base64'); res.set({ 'Content-Type': 'image/gif', 'Content-Length': pixel.length, 'Cache-Control': 'no-store, no-cache, must-revalidate, private', 'Pragma': 'no-cache', 'Expires': '0' }); res.send(pixel); });

app.get('/unsub/:leadId', (req, res) => { try { const result = db.unsubscribeLead(req.params.leadId); if (!result.found) return res.status(404).send('<h1>Link expired or invalid.</h1>'); res.send(`<!DOCTYPE html><html><head><meta charset="utf-8"><title>Unsubscribed</title></head><body style="font-family:Arial,sans-serif;text-align:center;padding:60px;color:#333;"><h1>Successfully unsubscribed</h1><p>You will no longer receive emails from us.</p><p style="color:#999;font-size:12px;">${result.email}</p></body></html>`); } catch (e) { console.error('Unsubscribe error:', e.message); res.status(500).send('<h1>An error occurred.</h1>'); } });

app.get('/api/campaigns/:id/logs', (req, res) => { res.json(db.getCampaignLogs(req.params.id)); });
app.get('/api/dashboard', (req, res) => { res.json(db.getDashboardStats()); });
app.get('*', (req, res) => { res.sendFile(path.join(__dirname, 'public', 'index.html')); });

const runScheduler = process.env.RUN_SCHEDULER !== 'false';
if (runScheduler) { scheduler.start(); } else { console.log('[Server] Scheduler disabled'); }

const PORT = process.env.PORT || 3000;
app.listen(PORT, '0.0.0.0', () => { const baseUrl = process.env.BASE_URL || `http://localhost:${PORT}`; console.log(`\n🚀 Cold Email Tool v2 running!\n   → ${baseUrl}\n   → Scheduler: ${runScheduler ? 'ON' : 'OFF'}\n   → DB: ${process.env.DB_PATH || './data.db'}\n`); });
