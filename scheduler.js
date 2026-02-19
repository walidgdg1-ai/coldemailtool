const cron = require('node-cron');
const { v4: uuidv4 } = require('uuid');
const db = require('./db');
const gmail = require('./gmail');

function randomDelay(minMs = 4000, maxMs = 15000) {
  return new Promise(resolve => setTimeout(resolve, Math.random() * (maxMs - minMs) + minMs));
}

function isInSendingWindow(lead) {
  const tz = lead.timezone || 'Europe/Paris';
  try {
    const now = new Date();
    const formatter = new Intl.DateTimeFormat('en-US', { timeZone: tz, hour: 'numeric', hour12: false, weekday: 'short' });
    const parts = formatter.formatToParts(now);
    const hourPart = parts.find(p => p.type === 'hour');
    const dayPart = parts.find(p => p.type === 'weekday');
    if (!hourPart || !dayPart) return true;
    let localHour = parseInt(hourPart.value, 10);
    if (localHour === 24) localHour = 0;
    const dayMap = { Sun: 0, Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6 };
    const localDay = dayMap[dayPart.value];
    if (localDay === undefined) return true;
    const allowedDays = (lead.send_days || '1,2,3,4,5').split(',').map(d => parseInt(d.trim(), 10)).filter(d => !isNaN(d));
    if (allowedDays.length > 0 && !allowedDays.includes(localDay)) return false;
    const startHour = lead.send_start_hour ?? 8;
    const endHour = lead.send_end_hour ?? 18;
    return localHour >= startHour && localHour < endHour;
  } catch (e) {
    console.error(`[Scheduler] Timezone error for "${tz}":`, e.message);
    return true;
  }
}

let isRunning = false;

async function processDueLeads() {
  if (isRunning) return;
  isRunning = true;
  try {
    const leads = db.getDueLeads(20);
    if (leads.length === 0) return;
    const eligibleLeads = leads.filter(isInSendingWindow);
    if (eligibleLeads.length === 0) return;
    console.log(`[Scheduler] Processing ${eligibleLeads.length} lead(s)...`);
    for (const lead of eligibleLeads) {
      if (db.hasLeadReplied(lead.id)) { console.log(`[Scheduler] Skipping ${lead.email} — replied`); continue; }
      const inbox = db.pickBestInbox(lead.id);
      if (!inbox) { console.log('[Scheduler] No available inbox. Stopping batch.'); break; }
      const step = db.getStep(lead.campaign_id, lead.current_step);
      if (!step) { const totalSteps = db.getTotalSteps(lead.campaign_id); db.markLeadSent(lead.id, totalSteps + 1, totalSteps, 0, inbox.id); continue; }
      const variation = db.pickVariation(step.id);
      if (!variation) { console.error(`[Scheduler] No variation for step ${step.id}`); continue; }
      const totalSteps = db.getTotalSteps(lead.campaign_id);
      const logId = uuidv4();
      db.logEmail({ id: logId, leadId: lead.id, campaignId: lead.campaign_id, stepNumber: lead.current_step, variant: variation.variant, inboxId: inbox.id, inboxEmail: inbox.email, subject: variation.subject, status: 'sending' });
      try {
        const { subject } = await gmail.sendEmail({ inboxId: inbox.id, to: lead.email, subject: variation.subject, body: variation.body, lead, logId, trackOpens: !!lead.track_opens, showUnsubscribe: !!lead.show_unsubscribe, unsubscribeText: lead.unsubscribe_text });
        db.updateLogStatus(logId, 'sent', subject, null);
        db.incrementInboxSentCount(inbox.id);
        const nextStep = db.getStep(lead.campaign_id, lead.current_step + 1);
        const delayDays = nextStep ? nextStep.delay_days : 0;
        db.markLeadSent(lead.id, lead.current_step + 1, totalSteps, delayDays, inbox.id);
        console.log(`[Scheduler] Sent step ${lead.current_step}${variation.variant !== 'A' ? ` (${variation.variant})` : ''} to ${lead.email} via ${inbox.email}`);
      } catch (err) {
        console.error(`[Scheduler] Failed ${lead.email} (attempt ${(lead.retry_count||0)+1}/3):`, err.message);
        db.updateLogStatus(logId, 'failed', null, err.message);
        db.incrementLeadRetry(lead.id);
      }
      await randomDelay(4000, 15000);
    }
  } catch (err) { console.error('[Scheduler] Unexpected error:', err); }
  finally { isRunning = false; }
}

function start() {
  console.log('[Scheduler] Started — checking every 60s');
  cron.schedule('* * * * *', () => { processDueLeads(); });
  cron.schedule('0 0 * * *', () => { console.log('[Scheduler] Midnight reset'); });
}

module.exports = { start, processDueLeads, isInSendingWindow };
